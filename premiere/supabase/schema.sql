-- Première : calendrier des prix SNCF, suivi et rames Océane
-- À coller dans Supabase > SQL Editor > New query > Run.
-- Toutes les tables commencent par train_ : elles peuvent vivre dans un projet
-- Supabase existant (Radar Prod, Loupe) sans rien toucher à ses autres tables.

create extension if not exists pgcrypto;

-- Recherches (une ligne = un trajet + une période, avec ou sans retour)
create table if not exists train_recherches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  nom text,
  origine text not null,
  destination text not null,
  aller_debut date not null,
  aller_fin date not null,
  retour_debut date,
  retour_fin date,
  nuits_min int not null default 1,
  nuits_max int,
  classe text not null default '1re' check (classe in ('1re', '2de')),
  inoui_seul boolean not null default true,
  via_paris boolean not null default false,
  voyageurs jsonb not null default '[{"age": 25, "carte": "Carte Avantage Jeune"}]',
  chiens int not null default 0 check (chiens between 0 and 2),
  suivi boolean not null default false,
  heure_suivi int not null default 8 check (heure_suivi between 0 and 23),
  seuil numeric,
  analyser_rames boolean not null default true,
  statut text not null default 'en_attente'
    check (statut in ('en_attente', 'en_cours', 'terminee', 'erreur', 'bloquee', 'pause')),
  progression int not null default 0,
  message text,
  derniere_execution timestamptz,
  prochaine_execution timestamptz default now(),
  archive boolean not null default false,
  created_at timestamptz not null default now()
);

-- Chaque passage du robot sur une recherche (permet de suivre l'évolution des prix)
create table if not exists train_executions (
  id uuid primary key default gen_random_uuid(),
  recherche_id uuid not null references train_recherches on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  debut timestamptz not null default now(),
  fin timestamptz,
  statut text not null default 'en_cours',
  meilleur_aller numeric,
  meilleur_retour numeric,
  meilleur_total numeric,
  message text
);

-- Les trains trouvés (une ligne par train et par passage)
create table if not exists train_releves (
  id bigint generated always as identity primary key,
  execution_id uuid not null references train_executions on delete cascade,
  recherche_id uuid not null references train_recherches on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  sens text not null check (sens in ('aller', 'retour')),
  jour date not null,
  depart text, arrivee text, duree text, correspondances text,
  trains text, tarif text, conditions text,
  via text,
  numeros text[],
  legs jsonb,
  prix numeric not null,
  chien numeric not null default 0,
  chien_estime boolean not null default false,
  total numeric not null,
  cle text,
  created_at timestamptz not null default now()
);
create index if not exists train_releves_exec on train_releves (execution_id, sens, jour);
create index if not exists train_releves_rech on train_releves (recherche_id, created_at);

-- Demandes d'analyse de rame (plan de salle d'un train précis)
create table if not exists train_analyses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  recherche_id uuid references train_recherches on delete set null,
  jour date not null,
  origine text not null,
  destination text not null,
  depart text not null,
  numero text,
  statut text not null default 'en_attente'
    check (statut in ('en_attente', 'en_cours', 'terminee', 'erreur')),
  message text,
  created_at timestamptz not null default now()
);

-- Voitures observées dans les plans de salle, avec leur empreinte
create table if not exists train_voitures (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  analyse_id uuid references train_analyses on delete set null,
  numero_train text not null,
  jour date not null,
  voiture int not null,
  classe text,
  signature text not null,
  resume jsonb not null,
  plan jsonb,
  created_at timestamptz not null default now()
);
create index if not exists train_voitures_sig on train_voitures (user_id, signature);
create index if not exists train_voitures_train on train_voitures (user_id, numero_train, jour);

-- Tes étiquettes sur les empreintes (« Océane », « à éviter »...)
create table if not exists train_etiquettes (
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  signature text not null,
  etiquette text not null,
  note text,
  created_at timestamptz not null default now(),
  primary key (user_id, signature)
);

-- Alertes de baisse de prix
create table if not exists train_alertes (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  recherche_id uuid not null references train_recherches on delete cascade,
  ancien numeric,
  nouveau numeric not null,
  detail text,
  lu boolean not null default false,
  created_at timestamptz not null default now()
);

-- État du robot du Mac (pour afficher « en ligne » dans l'app)
create table if not exists train_robot (
  user_id uuid primary key default auth.uid() references auth.users on delete cascade,
  vu_le timestamptz not null default now(),
  version text,
  occupe text
);

-- Sécurité : chacun ne voit que ses lignes (l'app ET le robot se connectent avec ton compte)
do $$
declare t text;
begin
  foreach t in array array['train_recherches','train_executions','train_releves','train_analyses',
                           'train_voitures','train_etiquettes','train_alertes','train_robot'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "proprietaire" on %I', t);
    execute format('create policy "proprietaire" on %I for all using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
  end loop;
end $$;

-- Mises à jour en direct dans l'app pendant que le robot travaille
do $$
begin
  begin execute 'alter publication supabase_realtime add table train_recherches'; exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table train_robot'; exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table train_analyses'; exception when others then null; end;
end $$;
