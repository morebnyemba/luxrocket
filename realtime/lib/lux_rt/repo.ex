defmodule LuxRt.Repo do
  use Ecto.Repo,
    otp_app: :lux_rt,
    adapter: Ecto.Adapters.Postgres
end
