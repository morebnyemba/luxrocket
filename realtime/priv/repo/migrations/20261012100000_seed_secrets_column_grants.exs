defmodule LuxRt.Repo.Migrations.SeedSecretsColumnGrants do
  @moduledoc """
  Other roles that can read `rt` (the platform, via infra/postgres/roles.sql default privileges)
  must never select encrypted seed material, even as ciphertext: `seed_checkpoint` becomes
  unreadable to them and `seed_chain` readable only column by column, without `root_seed_ct`.
  Re-run safe; a no-op on single-user databases.
  """
  use Ecto.Migration

  @public_columns ~w(chain_id stream_id length terminal_hash salt salt_source checkpoint_every
                     status inserted_at drand_chain_hash drand_round drand_signature committed_at
                     activated_at retired_at)

  def up do
    execute("""
    DO $$
    DECLARE g text;
    BEGIN
      FOR g IN
        SELECT DISTINCT grantee FROM information_schema.role_table_grants
         WHERE table_schema = 'rt' AND table_name IN ('seed_chain', 'seed_checkpoint')
           AND grantee <> current_user AND grantee <> 'PUBLIC'
      LOOP
        EXECUTE format('REVOKE ALL ON rt.seed_checkpoint FROM %I', g);
        EXECUTE format('REVOKE ALL ON rt.seed_chain FROM %I', g);
        EXECUTE format('GRANT SELECT (#{Enum.join(@public_columns, ", ")}) ON rt.seed_chain TO %I', g);
      END LOOP;
    END $$
    """)
  end

  def down, do: :ok
end
