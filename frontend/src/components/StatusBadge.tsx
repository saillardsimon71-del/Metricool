import type { PostStatus } from '../lib/types'
import { statusLabel } from '../lib/i18n'

const palette: Record<PostStatus, string> = {
  draft: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  ready: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  scheduled: 'bg-brand-500/15 text-brand-300 border-brand-500/30',
  waiting_for_user: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  uploading: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  processing: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  publishing: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  published: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  published_private: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  failed: 'bg-red-500/15 text-red-300 border-red-500/40',
  uncertain: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
  cancelled: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30',
}

export default function StatusBadge({ status, label }: { status: PostStatus; label?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${palette[status] ?? palette.draft}`}>
      {label ?? statusLabel(status)}
    </span>
  )
}
