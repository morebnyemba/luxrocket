defmodule LuxRt.Repo.Migrations.SeedChainCeremony do
  @moduledoc """
  Seed-chain lifecycle (doc 07 §6.1): COMMITTED (terminal hash and a future drand round are
  published, salt unknown) -> ACTIVE (salted from that drand round, four-eyes approved) ->
  RETIRED | EXHAUSTED. At most one ACTIVE chain per stream.
  """
  use Ecto.Migration

  def up do
    alter table(:seed_chain, prefix: "rt") do
      add :drand_chain_hash, :text
      add :drand_round, :bigint
      add :drand_signature, :text
      add :committed_at, :utc_datetime_usec
      add :activated_at, :utc_datetime_usec
      add :retired_at, :utc_datetime_usec
    end

    # Older builds could leave several ACTIVE rows per stream (the newest one was used).
    execute("""
    UPDATE rt.seed_chain c SET status = 'RETIRED', retired_at = now()
     WHERE c.status = 'ACTIVE' AND EXISTS (
       SELECT 1 FROM rt.seed_chain n
        WHERE n.stream_id = c.stream_id AND n.status = 'ACTIVE' AND n.inserted_at > c.inserted_at)
    """)

    execute("UPDATE rt.seed_chain SET activated_at = inserted_at WHERE status = 'ACTIVE'")

    create unique_index(:seed_chain, [:stream_id],
             prefix: "rt",
             where: "status = 'ACTIVE'",
             name: :seed_chain_one_active_per_stream
           )

    create constraint(:seed_chain, :seed_chain_status,
             prefix: "rt",
             check: "status IN ('COMMITTED', 'ACTIVE', 'RETIRED', 'EXHAUSTED')"
           )
  end

  def down do
    drop constraint(:seed_chain, :seed_chain_status, prefix: "rt")
    drop index(:seed_chain, [:stream_id], prefix: "rt", name: :seed_chain_one_active_per_stream)

    alter table(:seed_chain, prefix: "rt") do
      remove :drand_chain_hash
      remove :drand_round
      remove :drand_signature
      remove :committed_at
      remove :activated_at
      remove :retired_at
    end
  end
end
