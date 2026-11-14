import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/vizdrag'
const columns = [
  "方案编号",
  "方案名称",
  "数据源绑定",
  "图表类型",
  "横轴字段",
  "纵轴字段",
  "分组字段",
  "绑定版本",
  "方案状态"
]
const actions = [
  "发布方案",
  "嵌入看板",
  "归档方案"
]

type Row = Record<string, string | number | null>

interface BindingRules {
  datasources: Record<string, {
    dimensions: string[]
    measures: string[]
    groups: string[]
    chart_types: string[]
  }>
  limits: Record<string, number>
  slot_priority: string[]
  priority_text: string
}

interface BindingForm {
  数据源绑定: string
  图表类型: string
  横轴字段: string
  纵轴字段: string
  分组字段: string[]
}

const EMPTY_FORM: BindingForm = {
  数据源绑定: '',
  图表类型: '',
  横轴字段: '',
  纵轴字段: '',
  分组字段: [],
}

function toList(value: string | number | null | undefined): string[] {
  if (value === null || value === undefined) return []
  return String(value).split(/[,，;；]/).map((item) => item.trim()).filter(Boolean)
}

export default function VizdragView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [rules, setRules] = useState<BindingRules | null>(null)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form, setForm] = useState<BindingForm>(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState({ 方案编号: '', 方案名称: '', 数据源绑定: '' })
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('可视化方案列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '拖拽可视化列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    request(`${ENDPOINT}/rules`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error('绑定规则读取失败'))))
      .then((data: BindingRules) => setRules(data))
      .catch((error: unknown) => setErrorMessage(error instanceof Error ? error.message : '绑定规则读取失败'))
  }, [])

  const stats = useMemo(() => [
    { label: '可视化方案总数', value: rows.length },
    { label: '已发布方案', value: rows.filter((row) => row.status === '已发布').length },
    { label: '已嵌入方案', value: rows.filter((row) => row.status === '已嵌入').length },
  ], [rows])

  const activeSchema = useMemo(() => {
    if (!rules || !form.数据源绑定) return null
    return rules.datasources[form.数据源绑定] ?? null
  }, [rules, form.数据源绑定])

  function openEditor(row: Row) {
    setErrorMessage('')
    setFormError('')
    setEditing(row)
    setForm({
      数据源绑定: String(row['数据源绑定'] ?? ''),
      图表类型: String(row['图表类型'] ?? ''),
      横轴字段: String(row['横轴字段'] ?? ''),
      纵轴字段: String(row['纵轴字段'] ?? ''),
      分组字段: toList(row['分组字段']),
    })
  }

  function closeEditor() {
    setEditing(null)
    setFormError('')
    setSaving(false)
  }

  function toggleGroup(field: string) {
    setForm((prev) => {
      const limit = rules?.limits['分组字段'] ?? 2
      const exists = prev.分组字段.includes(field)
      if (exists) {
        return { ...prev, 分组字段: prev.分组字段.filter((item) => item !== field) }
      }
      if (prev.分组字段.length >= limit) {
        setFormError(`分组字段最多绑定 ${limit} 个，超过上限不允许保存，请先取消已选字段`)
        return prev
      }
      return { ...prev, 分组字段: [...prev.分组字段, field] }
    })
  }

  async function saveBinding() {
    if (!editing) return
    setSaving(true)
    setFormError('')
    try {
      const response = await request(`${ENDPOINT}/${editing.id}/bindings`, {
        method: 'POST',
        body: JSON.stringify({
          values: {
            expected_version: editing.binding_version,
            数据源绑定: form.数据源绑定,
            图表类型: form.图表类型,
            横轴字段: form.横轴字段,
            纵轴字段: form.纵轴字段,
            分组字段: form.分组字段.join(','),
          },
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        setFormError(payload.message ?? '字段绑定保存失败')
        return
      }
      setNotice(payload.message ?? '字段绑定已保存')
      closeEditor()
      await reload()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '字段绑定保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function createScheme() {
    setSaving(true)
    setFormError('')
    try {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: createForm }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        setFormError(payload.message ?? '可视化方案登记失败')
        return
      }
      setCreating(false)
      setCreateForm({ 方案编号: '', 方案名称: '', 数据源绑定: '' })
      setNotice(payload.message ?? '可视化方案已登记')
      await reload()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '可视化方案登记失败')
    } finally {
      setSaving(false)
    }
  }

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        setErrorMessage(payload.message ?? '拖拽可视化动作未生效，请稍后重试')
        return
      }
      setNotice(payload.message ?? '操作成功')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '拖拽可视化操作失败')
    }
  }

  return (
    <section className="page" data-module="vizdrag">
      <header className="page-head">
        <div>
          <h2>拖拽可视化管理</h2>
          <p className="page-desc">
            维护拖拽可视化的图表类型、数据绑定与分组配置；字段绑定按数据源允许范围准入，
            冲突优先级：{rules?.priority_text ?? '纵轴字段 > 横轴字段 > 分组字段'}，超过上限不允许保存。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => { setCreating(true); setFormError('') }}>
            登记可视化方案
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出拖拽可视化清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>绑定维护</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td>
                <button className="link" type="button" onClick={() => openEditor(row)}>编辑字段绑定</button>
              </td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无拖拽可视化数据，可先登记可视化方案</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条拖拽可视化记录</span>
        {notice && <span className="success-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {editing && rules && (
        <div className="modal-mask" onMouseDown={(event) => { if (event.target === event.currentTarget) closeEditor() }}>
          <div className="modal" role="dialog" aria-modal="true">
            <div className="modal-head">
              <h3>编辑字段绑定 · {String(editing['方案编号'])}（当前绑定版本 {String(editing.binding_version ?? 1)}）</h3>
              <button className="modal-close" type="button" onClick={closeEditor} aria-label="关闭">×</button>
            </div>
            <div className="form-grid">
              <label>数据源绑定</label>
              <div>
                <select
                  value={form.数据源绑定}
                  onChange={(event) => setForm({ ...EMPTY_FORM, 数据源绑定: event.target.value })}
                >
                  <option value="">请选择数据源</option>
                  {Object.keys(rules.datasources).map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </div>

              <label>图表类型</label>
              <div>
                <select
                  value={form.图表类型}
                  disabled={!activeSchema}
                  onChange={(event) => setForm((prev) => ({ ...prev, 图表类型: event.target.value }))}
                >
                  <option value="">请选择图表类型</option>
                  {activeSchema?.chart_types.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>

              <label>横轴字段（{rules.limits['横轴字段']} 个）</label>
              <div>
                <select
                  value={form.横轴字段}
                  disabled={!activeSchema}
                  onChange={(event) => setForm((prev) => ({ ...prev, 横轴字段: event.target.value }))}
                >
                  <option value="">未绑定</option>
                  {activeSchema?.dimensions.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
                <p className="form-hint">允许范围：{activeSchema?.dimensions.join('、') || '先选择数据源'}</p>
              </div>

              <label>纵轴字段（{rules.limits['纵轴字段']} 个）</label>
              <div>
                <select
                  value={form.纵轴字段}
                  disabled={!activeSchema}
                  onChange={(event) => setForm((prev) => ({ ...prev, 纵轴字段: event.target.value }))}
                >
                  <option value="">未绑定</option>
                  {activeSchema?.measures.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
                <p className="form-hint">允许范围：{activeSchema?.measures.join('、') || '先选择数据源'}</p>
              </div>

              <label>分组字段（最多 {rules.limits['分组字段']} 个）</label>
              <div className="check-list">
                {activeSchema?.groups.map((name) => (
                  <label key={name}>
                    <input
                      type="checkbox"
                      checked={form.分组字段.includes(name)}
                      onChange={() => toggleGroup(name)}
                    />
                    {name}
                  </label>
                ))}
                {!activeSchema && <span className="form-hint">先选择数据源后展示允许的分组字段</span>}
              </div>
            </div>
            <p className="form-hint">
              冲突唯一优先级：{rules.priority_text}；同一字段不允许重复或跨位置绑定，否则后端拒绝保存。
            </p>
            {formError && <p className="form-error">{formError}</p>}
            <div className="modal-foot">
              <button className="btn ghost" type="button" onClick={closeEditor}>取消</button>
              <button className="btn primary" type="button" disabled={saving} onClick={() => void saveBinding()}>
                {saving ? '保存中…' : '保存绑定'}
              </button>
            </div>
          </div>
        </div>
      )}

      {creating && rules && (
        <div className="modal-mask" onMouseDown={(event) => { if (event.target === event.currentTarget) setCreating(false) }}>
          <div className="modal" role="dialog" aria-modal="true">
            <div className="modal-head">
              <h3>登记可视化方案</h3>
              <button className="modal-close" type="button" onClick={() => setCreating(false)} aria-label="关闭">×</button>
            </div>
            <div className="form-grid">
              <label>方案编号</label>
              <input
                value={createForm.方案编号}
                placeholder="例如 VIZD-0004"
                onChange={(event) => setCreateForm((prev) => ({ ...prev, 方案编号: event.target.value }))}
              />
              <label>方案名称</label>
              <input
                value={createForm.方案名称}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, 方案名称: event.target.value }))}
              />
              <label>数据源绑定</label>
              <select
                value={createForm.数据源绑定}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, 数据源绑定: event.target.value }))}
              >
                <option value="">请选择数据源</option>
                {Object.keys(rules.datasources).map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </div>
            {formError && <p className="form-error">{formError}</p>}
            <div className="modal-foot">
              <button className="btn ghost" type="button" onClick={() => setCreating(false)}>取消</button>
              <button className="btn primary" type="button" disabled={saving} onClick={() => void createScheme()}>
                {saving ? '提交中…' : '登记'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
