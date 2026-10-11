import Config

# Configure your database
#
# The MIX_TEST_PARTITION environment variable can be used
# to provide built-in test partitioning in CI environment.
# Run `mix help test` for more information.
config :lux_rt, LuxRt.Repo,
  username: System.get_env("POSTGRES_USER", "luxrocket"),
  password: System.get_env("POSTGRES_PASSWORD", "luxrocket-dev-only"),
  hostname: System.get_env("POSTGRES_HOST", "localhost"),
  port: String.to_integer(System.get_env("POSTGRES_PORT", "5432")),
  database: "lux_rt_test#{System.get_env("MIX_TEST_PARTITION")}",
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: System.schedulers_online() * 2

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :lux_rt, LuxRtWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base:
    System.get_env("SECRET_KEY_BASE", String.duplicate("test-only-not-a-secret-", 4)),
  server: false

# Print only warnings and errors during test
config :logger, level: :warning

# Initialize plugs at runtime for faster test compilation
config :phoenix, :plug_init_mode, :runtime

# Tests start coordinators explicitly with short timings.
config :lux_rt, :start_coordinators, false
config :lux_rt, :start_relay, false
config :lux_rt, :platform_client, LuxRt.PlatformStub

config :lux_rt, :fairness,
  chain_length: 2_000,
  checkpoint_every: 100,
  seed_kek_b64: "ZGV2LW9ubHktbm90LWEtc2VjcmV0LXNlZWQta2V5ISE="

# A 50x faster curve keeps every test flight under ~3 s (10 000x is reached at ~3.1 s).
config :lux_rt, :ruleset,
  house_edge_bp: 300,
  max_multiplier_x10000: 100_000_000,
  curve_lambda_per_ms: "0.003",
  panels: 2
