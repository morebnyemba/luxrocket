defmodule LuxRt.Repo.Migrations.CreateRtSchema do
  @moduledoc "Phoenix-owned round facts (doc 04 §4.8). Django has read access only."
  use Ecto.Migration

  def change do
    create table(:stream_lease, primary_key: false, prefix: "rt") do
      add :stream_id, :text, primary_key: true
      add :holder, :text, null: false
      add :fencing_token, :bigint, null: false, default: 0
      add :expires_at, :utc_datetime_usec, null: false
    end

    create table(:seed_chain, primary_key: false, prefix: "rt") do
      add :chain_id, :uuid, primary_key: true
      add :stream_id, :text, null: false
      add :length, :bigint, null: false
      add :terminal_hash, :text, null: false
      add :salt, :text, null: false
      add :salt_source, :text, null: false
      add :root_seed_ct, :binary, null: false
      add :checkpoint_every, :integer, null: false
      add :status, :text, null: false
      timestamps(type: :utc_datetime_usec, updated_at: false)
    end

    create index(:seed_chain, [:stream_id, :status], prefix: "rt")

    create table(:seed_checkpoint, primary_key: false, prefix: "rt") do
      add :chain_id, references(:seed_chain, column: :chain_id, type: :uuid, prefix: "rt"),
        primary_key: true

      add :idx, :bigint, primary_key: true
      add :seed_ct, :binary, null: false
    end

    create table(:round, primary_key: false, prefix: "rt") do
      add :round_id, :uuid, primary_key: true
      add :stream_id, :text, null: false
      add :number, :bigint, null: false
      add :chain_id, :uuid, null: false
      add :chain_index, :bigint, null: false
      add :state, :text, null: false
      add :commitment, :text, null: false
      add :opens_at, :bigint
      add :close_at, :bigint
      add :launch_at, :bigint
      add :crash_at, :bigint
      # Never written before the crash (doc 04 §4.8).
      add :crash_x10000, :integer
      add :seed_hex, :text
      add :fencing_token, :bigint, null: false
      timestamps(type: :utc_datetime_usec)
    end

    create unique_index(:round, [:stream_id, :number], prefix: "rt")
    create unique_index(:round, [:chain_id, :chain_index], prefix: "rt")

    create table(:round_journal, primary_key: false, prefix: "rt") do
      add :journal_id, :bigserial, primary_key: true
      add :stream_id, :text, null: false
      add :stream_seq, :bigint, null: false
      add :event_id, :uuid, null: false
      add :round_id, :uuid, null: false
      add :type, :text, null: false
      add :payload, :map, null: false
      add :fencing_token, :bigint, null: false
      add :recorded_at, :utc_datetime_usec, null: false
      add :relayed_at, :utc_datetime_usec
    end

    create unique_index(:round_journal, [:stream_id, :stream_seq], prefix: "rt")
    create unique_index(:round_journal, [:event_id], prefix: "rt")

    create index(:round_journal, [:stream_id, :stream_seq],
             prefix: "rt",
             where: "relayed_at IS NULL",
             name: :round_journal_unrelayed
           )

    # Append-only: facts are never updated or deleted, except marking relay progress.
    execute(
      """
      CREATE OR REPLACE FUNCTION rt.journal_append_only() RETURNS trigger AS $$
      BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'round_journal is append-only'; END IF;
        IF (OLD.stream_id, OLD.stream_seq, OLD.event_id, OLD.round_id, OLD.type, OLD.payload,
            OLD.fencing_token, OLD.recorded_at)
           IS DISTINCT FROM
           (NEW.stream_id, NEW.stream_seq, NEW.event_id, NEW.round_id, NEW.type, NEW.payload,
            NEW.fencing_token, NEW.recorded_at)
        THEN RAISE EXCEPTION 'round_journal facts are immutable'; END IF;
        RETURN NEW;
      END $$ LANGUAGE plpgsql
      """,
      "DROP FUNCTION IF EXISTS rt.journal_append_only()"
    )

    execute(
      """
      CREATE TRIGGER journal_append_only BEFORE UPDATE OR DELETE ON rt.round_journal
      FOR EACH ROW EXECUTE FUNCTION rt.journal_append_only()
      """,
      "DROP TRIGGER IF EXISTS journal_append_only ON rt.round_journal"
    )
  end
end
