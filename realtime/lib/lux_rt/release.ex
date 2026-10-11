defmodule LuxRt.Release do
  @moduledoc "Release tasks: `bin/lux_rt eval \"LuxRt.Release.migrate()\"`."
  @app :lux_rt

  def migrate do
    Application.ensure_all_started(:ssl)
    Application.load(@app)

    for repo <- Application.fetch_env!(@app, :ecto_repos) do
      {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :up, all: true))
    end
  end
end
