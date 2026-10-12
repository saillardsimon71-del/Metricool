import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, KeyRound, ShieldAlert, ShieldCheck, Star, Unplug, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/AppShell'
import PlatformIcon, { platformLabel } from '../components/PlatformIcon'
import { Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { formatRelative } from '../lib/format'
import { useToasts } from '../hooks/useToasts'
import type { Account, Platform } from '../lib/types'

const guides: Record<string, { docs: string; steps: string[] }> = {
  youtube: {
    docs: 'docs/CONNECT_YOUTUBE.md',
    steps: [
      'Créez un projet sur console.cloud.google.com et activez « YouTube Data API v3 ».',
      'Configurez l’écran de consentement OAuth (type Externe) et ajoutez votre adresse en utilisateur de test.',
      'Créez des identifiants « Application de bureau » puis renseignez SOCIALDOCK_GOOGLE_CLIENT_ID / _SECRET dans .env.',
      'Déclarez l’URL de redirection http://127.0.0.1:8000/api/oauth/youtube/callback.',
    ],
  },
  instagram: {
    docs: 'docs/CONNECT_INSTAGRAM.md',
    steps: [
      'Créez une application sur developers.facebook.com et ajoutez le produit Instagram.',
      'Passez votre compte Instagram en Professionnel (Business ou Creator).',
      'Demandez les permissions instagram_business_basic et instagram_business_content_publish (accès Standard suffit pour vos propres comptes).',
      'Renseignez SOCIALDOCK_META_APP_ID / _SECRET et l’URL de redirection http://127.0.0.1:8000/api/oauth/instagram/callback.',
    ],
  },
  tiktok: {
    docs: 'docs/CONNECT_TIKTOK.md',
    steps: [
      'Créez une application sur developers.tiktok.com (Login Kit + Content Posting API).',
      'Demandez les scopes user.info.basic, video.publish et video.upload.',
      'Renseignez SOCIALDOCK_TIKTOK_CLIENT_KEY / _SECRET et la redirection http://127.0.0.1:8000/api/oauth/tiktok/callback.',
      'Sans audit TikTok, la publication restera privée (SELF_ONLY) : SocialDock l’indique explicitement.',
    ],
  },
}

export default function Accounts() {
  const [wizard, setWizard] = useState<Platform | null>(null)
  const [renaming, setRenaming] = useState<Account | null>(null)
  const [name, setName] = useState('')
  const queryClient = useQueryClient()
  const { notify } = useToasts()

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/api/accounts') })

  const seed = useMutation({
    mutationFn: () => api.post<Account[]>('/api/accounts/demo/seed'),
    onSuccess: () => { notify('Comptes de démonstration prêts', 'success'); queryClient.invalidateQueries() },
    onError: (error) => notify(error.message, 'error'),
  })

  const create = useMutation({
    mutationFn: (body: { platform: string; display_name: string; mode?: string }) => api.post<Account>('/api/accounts', body),
    onSuccess: () => { notify('Compte créé : lancez la connexion', 'success'); queryClient.invalidateQueries() },
    onError: (error) => notify(error.message, 'error'),
  })

  const verify = useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean; message?: string }>(`/api/accounts/${id}/verify`),
    onSuccess: (result) => {
      notify(result.message ?? (result.ok ? 'Compte joignable' : 'Vérification échouée'), result.ok ? 'success' : 'error')
      queryClient.invalidateQueries()
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const oauth = useMutation({
    mutationFn: (id: string) => api.post<{ authorization_url: string; notes: string[] }>(`/api/accounts/${id}/oauth/start`),
    onSuccess: (result) => {
      notify('Fenêtre d’autorisation ouverte dans un nouvel onglet', 'info')
      window.open(result.authorization_url, '_blank', 'noopener')
    },
    onError: (error) => notify(error.message, 'error'),
  })

  const disconnect = useMutation({
    mutationFn: (id: string) => api.post<Account>(`/api/accounts/${id}/disconnect`),
    onSuccess: () => { notify('Compte déconnecté (jetons révoqués)', 'warning'); queryClient.invalidateQueries() },
    onError: (error) => notify(error.message, 'error'),
  })

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch<Account>(`/api/accounts/${id}`, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['accounts'] }); notify('Compte mis à jour', 'success') },
    onError: (error) => notify(error.message, 'error'),
  })

  if (accounts.isLoading) return <Spinner label="Chargement des comptes…" />
  if (accounts.error) return <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} />

  return (
    <div>
      <PageHeader
        title="Comptes"
        description="Chaque compte affiche ses capacités réelles : un compte non audité n’est jamais présenté comme capable de publier publiquement."
        actions={
          <>
            <Button onClick={() => seed.mutate()} loading={seed.isPending}><UserPlus size={16} /> Six comptes démo</Button>
            <Button variant="primary" onClick={() => setWizard('youtube')}>Connecter un compte</Button>
          </>
        }
      />

      {accounts.data!.length === 0 && (
        <EmptyState
          title="Aucun compte"
          description="Commencez par six comptes de démonstration pour explorer l’application, puis connectez vos comptes réels."
          action={<Button variant="primary" onClick={() => seed.mutate()}>Créer les comptes de démonstration</Button>}
        />
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {accounts.data!.map((account) => {
          const capabilities = account.capabilities
          return (
            <Card key={account.id} className="space-y-3">
              <header className="flex items-start gap-3">
                <PlatformIcon platform={account.platform} size={22} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{account.display_name}</p>
                  <p className="text-xs text-ink-muted">
                    {platformLabel(account.platform)} · {account.mode === 'demo' ? 'Démonstration locale' : `Compte réel · ${account.status}`}
                    {account.username ? ` · ${account.username}` : ''}
                  </p>
                  {account.last_verified_at && <p className="text-xs text-ink-faint">Vérifié {formatRelative(account.last_verified_at)}</p>}
                </div>
                <button aria-label="Favori" onClick={() => patch.mutate({ id: account.id, body: { is_favorite: !account.is_favorite } })}>
                  <Star size={16} className={account.is_favorite ? 'fill-amber-400 text-amber-400' : 'text-ink-faint'} />
                </button>
              </header>

              <div className="flex flex-wrap gap-1 text-xs">
                <span className={`chip ${capabilities?.publish_public ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                  {capabilities?.publish_public ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
                  Publication publique : {capabilities?.publish_public ? 'autorisée' : 'non autorisée'}
                </span>
                <span className="chip">Programmation native : {capabilities?.scheduling ? 'oui' : 'non'}</span>
                <span className="chip">Statistiques : {capabilities?.analytics ? 'oui' : 'non'}</span>
                <span className="chip">Mode assisté : {capabilities?.assisted_mode ? 'oui' : 'non'}</span>
              </div>

              {(capabilities?.restrictions ?? []).length > 0 && (
                <ul className="space-y-0.5 text-xs text-ink-muted">{(capabilities?.restrictions ?? []).map((line) => <li key={line}>• {line}</li>)}</ul>
              )}

              {(account.permissions_missing ?? []).length > 0 && (
                <p className="text-xs text-amber-300">Configuration manquante : {(account.permissions_missing ?? []).join(', ')}</p>
              )}
              {account.last_error && <p className="text-xs text-red-300">{account.last_error}</p>}

              <div className="flex flex-wrap gap-2">
                {account.mode !== 'demo' && <Button onClick={() => oauth.mutate(account.id)} loading={oauth.isPending}><KeyRound size={14} /> Connecter / reconnecter</Button>}
                <Button onClick={() => verify.mutate(account.id)} loading={verify.isPending}>Tester</Button>
                <Button onClick={() => { setRenaming(account); setName(account.display_name) }}>Renommer</Button>
                {account.platform !== 'demo' && account.mode === 'demo' && (
                  <Select
                    value={String(account.extra?.demo_scenario ?? '')}
                    onChange={(event) => patch.mutate({ id: account.id, body: { demo_scenario: event.target.value } })}
                    className="w-56"
                  >
                    <option value="">Scénario aléatoire (déterministe)</option>
                    <option value="success">Toujours : succès</option>
                    <option value="published_private">Toujours : publié en privé</option>
                    <option value="waiting_for_user">Toujours : action humaine</option>
                    <option value="failure">Toujours : échec</option>
                    <option value="uncertain">Toujours : statut incertain</option>
                  </Select>
                )}
                {account.platform !== 'demo' && account.mode !== 'demo' && (
                  <label className="flex items-center gap-2 text-xs text-ink-muted">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-brand-500"
                      checked={Boolean(account.extra?.audit_passed)}
                      onChange={(event) => patch.mutate({ id: account.id, body: { audit_passed: event.target.checked } })}
                    />
                    Audit de la plateforme réussi (débloque la publication publique)
                  </label>
                )}
                <Button variant="danger" onClick={() => disconnect.mutate(account.id)}><Unplug size={14} /> Déconnecter</Button>
              </div>
            </Card>
          )
        })}
      </div>

      <Modal open={wizard !== null} title="Assistant de connexion" onClose={() => setWizard(null)}>
        {wizard && (
          <div className="space-y-4">
            <div className="flex gap-2">
              {(['youtube', 'instagram', 'tiktok'] as Platform[]).map((platform) => (
                <button
                  key={platform}
                  onClick={() => setWizard(platform)}
                  className={`flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm ${wizard === platform ? 'border-brand-500 bg-brand-500/10' : ''}`}
                >
                  <PlatformIcon platform={platform} /> {platformLabel(platform)}
                </button>
              ))}
            </div>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-muted">
              {guides[wizard].steps.map((step) => <li key={step}>{step}</li>)}
            </ol>
            <p className="text-xs text-ink-faint">Guide complet : {guides[wizard].docs}</p>
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault()
                const data = new FormData(event.currentTarget)
                create.mutate({ platform: wizard, display_name: String(data.get('name') || platformLabel(wizard)) })
                setWizard(null)
              }}
            >
              <Field label="Nom local du compte"><Input name="name" placeholder={`${platformLabel(wizard)} principal`} required /></Field>
              <Button type="submit" variant="primary">Créer le compte</Button>
            </form>
          </div>
        )}
      </Modal>

      <Modal
        open={renaming !== null}
        title="Renommer le compte"
        onClose={() => setRenaming(null)}
        footer={<><Button onClick={() => setRenaming(null)}>Annuler</Button><Button variant="primary" onClick={() => { if (renaming) patch.mutate({ id: renaming.id, body: { display_name: name } }); setRenaming(null) }}>Enregistrer</Button></>}
      >
        <Field label="Nom affiché"><Input value={name} onChange={(event) => setName(event.target.value)} /></Field>
      </Modal>
    </div>
  )
}

export { ExternalLink }
