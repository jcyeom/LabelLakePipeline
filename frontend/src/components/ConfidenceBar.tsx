export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="text-xs text-gray-400">-</span>
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? 'bg-green-500' : value >= 0.6 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-gray-200">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-600">{pct}%</span>
    </div>
  )
}
