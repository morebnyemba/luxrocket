import Config

# config/runtime.exs is executed for all environments, including
# during releases. It is executed after compilation and before the
# system starts, so it is typically used to load production configuration
# and secrets from environment variables or elsewhere. Do not define
# any compile-time configuration in here, as it won't be applied.
# The block below contains prod specific runtime configuration.

# ## Using releases
#
# If you use `mix release`, you need to explicitly enable the server
# by passing the PHX_SERVER=true when you start it:
#
#     PHX_SERVER=true bin/lux_rt start
#
# Alternatively, you can use `mix phx.gen.release` to generate a `bin/server`
# script that automatically sets the env var above.
if System.get_env("PHX_SERVER") do
  config :lux_rt, LuxRtWeb.Endpoint, server: true
end

# Platform integration and origins come from the environment in every deployed environment.
if url = System.get_env("PLATFORM_INTERNAL_URL") do
  config :lux_rt, :platform,
    base_url: url,
    service_token: System.fetch_env!("INTERNAL_SERVICE_TOKEN"),
    bet_timeout_ms: String.to_integer(System.get_env("BET_TIMEOUT_MS", "900"))
end

# Optional timing overrides (staging/E2E). Production uses the certified ruleset defaults.
timing_env = %{
  betting_window_ms: "BETTING_WINDOW_MS",
  close_grace_ms: "CLOSE_GRACE_MS",
  cooldown_ms: "COOLDOWN_MS"
}

overrides =
  for {key, var} <- timing_env, value = System.get_env(var), do: {key, String.to_integer(value)}

if overrides != [] do
  config :lux_rt, :timing, Keyword.merge(Application.get_env(:lux_rt, :timing, []), overrides)
end

if origins = System.get_env("GAME_ORIGINS") do
  config :lux_rt, :game_origins, String.split(origins, ",", trim: true)
end

if kek = System.get_env("SEED_KEK_B64") do
  config :lux_rt, :fairness,
    chain_length: String.to_integer(System.get_env("SEED_CHAIN_LENGTH", "1000000")),
    checkpoint_every: 1_000,
    seed_kek_b64: kek
end

if config_env() == :prod and is_nil(System.get_env("SEED_KEK_B64")) do
  raise "SEED_KEK_B64 is required in production (32-byte key, base64)"
end

if config_env() == :prod do
  database_url =
    System.get_env("DATABASE_URL") ||
      raise """
      environment variable DATABASE_URL is missing.
      For example: ecto://USER:PASS@HOST/DATABASE
      """

  maybe_ipv6 = if System.get_env("ECTO_IPV6") in ~w(true 1), do: [:inet6], else: []

  config :lux_rt, LuxRt.Repo,
    # ssl: true,
    url: database_url,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "10"),
    socket_options: maybe_ipv6

  # The secret key base is used to sign/encrypt cookies and other secrets.
  # A default value is used in config/dev.exs and config/test.exs but you
  # want to use a different value for prod and you most likely don't want
  # to check this value into version control, so we use an environment
  # variable instead.
  secret_key_base =
    System.get_env("SECRET_KEY_BASE") ||
      raise """
      environment variable SECRET_KEY_BASE is missing.
      You can generate one by calling: mix phx.gen.secret
      """

  host = System.get_env("PHX_HOST") || "example.com"
  port = String.to_integer(System.get_env("PORT") || "4000")

  config :lux_rt, :dns_cluster_query, System.get_env("DNS_CLUSTER_QUERY")

  config :lux_rt, LuxRtWeb.Endpoint,
    url: [host: host, port: 443, scheme: "https"],
    http: [
      # Enable IPv6 and bind on all interfaces.
      # Set it to  {0, 0, 0, 0, 0, 0, 0, 1} for local network only access.
      # See the documentation on https://hexdocs.pm/bandit/Bandit.html#t:options/0
      # for details about using IPv6 vs IPv4 and loopback vs public addresses.
      # PHX_IPV6=true binds dual-stack "::"; default is IPv4 any, which works on every host.
      ip:
        if(System.get_env("PHX_IPV6") in ~w(true 1),
          do: {0, 0, 0, 0, 0, 0, 0, 0},
          else: {0, 0, 0, 0}
        ),
      port: port
    ],
    secret_key_base: secret_key_base

  # ## SSL Support
  #
  # To get SSL working, you will need to add the `https` key
  # to your endpoint configuration:
  #
  #     config :lux_rt, LuxRtWeb.Endpoint,
  #       https: [
  #         ...,
  #         port: 443,
  #         cipher_suite: :strong,
  #         keyfile: System.get_env("SOME_APP_SSL_KEY_PATH"),
  #         certfile: System.get_env("SOME_APP_SSL_CERT_PATH")
  #       ]
  #
  # The `cipher_suite` is set to `:strong` to support only the
  # latest and more secure SSL ciphers. This means old browsers
  # and clients may not be supported. You can set it to
  # `:compatible` for wider support.
  #
  # `:keyfile` and `:certfile` expect an absolute path to the key
  # and cert in disk or a relative path inside priv, for example
  # "priv/ssl/server.key". For all supported SSL configuration
  # options, see https://hexdocs.pm/plug/Plug.SSL.html#configure/1
  #
  # We also recommend setting `force_ssl` in your config/prod.exs,
  # ensuring no data is ever sent via http, always redirecting to https:
  #
  #     config :lux_rt, LuxRtWeb.Endpoint,
  #       force_ssl: [hsts: true]
  #
  # Check `Plug.SSL` for all available options in `force_ssl`.
end
