defmodule Mix.Tasks.Lux.SeedCeremony do
  @shortdoc "Commits a new seed chain for a stream (doc 07 §6.1)"
  @moduledoc """
      mix lux.seed_ceremony --stream global [--delay-s 86400]

  Prints the public commitment (chain id, terminal hash, drand round). The chain stays
  COMMITTED until a four-eyes activation once that drand round is published.
  """
  use Mix.Task

  @impl true
  def run(args) do
    {opts, _, _} = OptionParser.parse(args, strict: [stream: :string, delay_s: :integer])
    Mix.Task.run("app.config")
    {:ok, _} = Application.ensure_all_started(:postgrex)
    {:ok, _} = Application.ensure_all_started(:ecto_sql)
    {:ok, _} = LuxRt.Repo.start_link()
    stream = Keyword.get(opts, :stream, "global")
    ceremony = Keyword.take(opts, [:delay_s])

    case LuxRt.Fairness.SeedChain.commit(stream, ceremony) do
      {:ok, facts} -> Mix.shell().info(Jason.encode!(facts, pretty: true))
      {:error, why} -> Mix.raise("ceremony refused: " <> why)
    end
  end
end
