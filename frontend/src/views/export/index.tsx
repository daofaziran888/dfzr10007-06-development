import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/export'
const columns = [
  "任务编号",
  "数据源名称",
  "导出格式",
  "字段选择",
  "筛选条件",
  "导出上限",
  "同步来源",
  "验收结论",
  "任务状态"
]
const actions = [
  "开始导出",
  "标记完成",
  "清理文件"
]

type Row = Record<string, string | number | null>

export default function ExportView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [syncing, setSyncing] = useState(false)
  const filterFields = useMemo(() => ["任务编号", "数据源名称", "导出格式"], [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('导出任务列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析导出中心列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = useMemo(() => [
    { label: '导出任务总数', value: rows.length },
    { label: '导出中任务', value: rows.filter((row) => row.status === '导出中').length },
    {
      label: '方案同步任务',
      value: rows.filter((row) => Boolean(row['同步来源'])).length,
    },
  ], [rows])

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
        setErrorMessage(payload.message ?? '分析导出中心动作未生效，请稍后重试')
        return
      }
      setNotice(payload.message ?? '操作成功')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析导出中心操作失败')
    }
  }

  async function syncVizdrag() {
    setSyncing(true)
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/sync-vizdrag`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        setErrorMessage(payload.message ?? '可视化方案同步失败')
        return
      }
      setNotice(payload.message ?? '同步完成')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '可视化方案同步失败')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <section className="page" data-module="export">
      <header className="page-head">
        <div>
          <h2>分析导出中心管理</h2>
          <p className="page-desc">
            维护分析导出的格式配置、字段选择与容量控制；拖拽可视化方案发布后自动同步到这里，
            按字段规则（横轴 1、纵轴 1、分组 2、字段总数 4）验收，同一方案编号只保留一份任务。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" disabled={syncing} onClick={() => void syncVizdrag()}>
            {syncing ? '同步中…' : '同步可视化发布结果'}
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出分析导出中心清单
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
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => (
                <td key={column}>
                  {column === '验收结论' && row[column] ? (
                    <span className={`tag ${row[column] === '验收通过' ? 'ok' : 'bad'}`}>
                      {String(row[column])}
                    </span>
                  ) : (
                    (row[column] ?? '—')
                  )}
                </td>
              ))}
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
              <td className="empty-state" colSpan={columns.length + 1}>暂无分析导出中心数据，可先登记导出任务</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条分析导出中心记录</span>
        {notice && <span className="success-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
