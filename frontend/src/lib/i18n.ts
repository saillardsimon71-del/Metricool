/** Internationalisation minimale et extensible : français par défaut. */

export type Locale = 'fr' | 'en'

interface Dictionary {
  app: { name: string; tagline: string }
  nav: Record<'dashboard' | 'calendar' | 'posts' | 'media' | 'accounts' | 'analytics' | 'automations' | 'settings' | 'diagnostics', string>
  status: Record<string, string>
  common: Record<'save' | 'cancel' | 'delete' | 'confirm' | 'close' | 'loading' | 'empty' | 'error' | 'demo' | 'real', string>
}

const fr: Dictionary = {
  app: {
    name: 'SocialDock',
    tagline: 'Gestionnaire local de réseaux sociaux',
  },
  nav: {
    dashboard: 'Tableau de bord',
    calendar: 'Calendrier',
    posts: 'Publications',
    media: 'Bibliothèque',
    accounts: 'Comptes',
    analytics: 'Statistiques',
    automations: 'Automatisations',
    settings: 'Paramètres',
    diagnostics: 'Diagnostics',
  },
  status: {
    draft: 'Brouillon',
    ready: 'Prête',
    scheduled: 'Programmée',
    waiting_for_user: 'Action humaine requise',
    uploading: 'Envoi en cours',
    processing: 'Traitement plateforme',
    publishing: 'Publication en cours',
    published: 'Publiée',
    published_private: 'Publiée (privée)',
    failed: 'Échec',
    uncertain: 'Statut incertain',
    cancelled: 'Annulée',
  },
  common: {
    save: 'Enregistrer',
    cancel: 'Annuler',
    delete: 'Supprimer',
    confirm: 'Confirmer',
    close: 'Fermer',
    loading: 'Chargement…',
    empty: 'Aucun élément pour le moment',
    error: 'Une erreur est survenue',
    demo: 'Démonstration',
    real: 'Compte réel',
  },
}

const en: Dictionary = {
  ...fr,
  app: { name: 'SocialDock', tagline: 'Local social media manager' },
  nav: {
    dashboard: 'Dashboard', calendar: 'Calendar', posts: 'Posts', media: 'Library', accounts: 'Accounts',
    analytics: 'Analytics', automations: 'Automations', settings: 'Settings', diagnostics: 'Diagnostics',
  },
  common: { ...fr.common, save: 'Save', cancel: 'Cancel', delete: 'Delete', confirm: 'Confirm', close: 'Close', loading: 'Loading…', empty: 'Nothing here yet', error: 'Something went wrong', demo: 'Demo', real: 'Real account' },
}

const dictionaries: Record<Locale, Dictionary> = { fr, en }

export const t = (locale: Locale, path: string): string => {
  const value = path.split('.').reduce<unknown>((acc, key) => (acc as Record<string, unknown>)?.[key], dictionaries[locale] ?? dictionaries.fr)
  return typeof value === 'string' ? value : path
}

export const statusLabel = (status: string, locale: Locale = 'fr'): string => dictionaries[locale].status[status] ?? status
