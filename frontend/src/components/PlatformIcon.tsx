import { FlaskConical, Instagram, Music2, Youtube } from 'lucide-react'

const config: Record<string, { Icon: typeof Youtube; className: string; label: string }> = {
  youtube: { Icon: Youtube, className: 'text-red-500', label: 'YouTube' },
  instagram: { Icon: Instagram, className: 'text-pink-500', label: 'Instagram' },
  tiktok: { Icon: Music2, className: 'text-ink', label: 'TikTok' },
  demo: { Icon: FlaskConical, className: 'text-brand-400', label: 'Démonstration' },
}

export default function PlatformIcon({ platform, size = 16 }: { platform?: string | null; size?: number }) {
  const entry = config[platform ?? 'demo'] ?? config.demo
  const { Icon } = entry
  return <Icon aria-label={entry.label} className={entry.className} size={size} />
}

export const platformLabel = (platform?: string | null): string => config[platform ?? 'demo']?.label ?? 'Démonstration'
