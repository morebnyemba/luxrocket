defmodule LuxRt.Release do
  @moduledoc """
  Release tasks:

    * `bin/lux_rt eval "LuxRt.Release.migrate()"`
    * `bin/lux_rt eval 'LuxRt.Release.seed_ceremony("global")'` — commits a new seed chain
      (doc 07 §6.1). Run by a key holder; activation then needs a four-eyes approval in the
      platform console once the committed drand round is published.
  """
  @app :lux_rt

  def migrate do
    Application.ensure_all_started(:ssl)
    Application.load(@app)

    for repo <- Application.fetch_env!(@app, :ecto_repos) do
      {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :up, all: true))
    end
  end

  def seed_ceremony(stream, opts \\ []) do
    Application.ensure_all_started(:ssl)
    Application.load(@app)

    {:ok, result, _} =
      Ecto.Migrator.with_repo(LuxRt.Repo, fn _ ->
        LuxRt.Fairness.SeedChain.commit(stream, opts)
      end)

    case result do
      {:ok, facts} ->
        IO.puts(Jason.encode!(facts, pretty: true))
        facts

      {:error, why} ->
        IO.puts(:stderr, "ceremony refused: " <> why)
        System.halt(1)
    end
  end
end
