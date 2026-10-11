defmodule LuxRt.Rounds.Snapshot do
  @moduledoc """
  Node-local public round snapshot (doc 06 §6). Joins and resyncs read ETS, never the
  coordinator, so reconnect storms do not hit the coordinator process.
  """

  @table :lux_rt_snapshots

  @doc "Creates the table; called once by `LuxRt.Tables`, which owns it."
  def init do
    :ets.new(@table, [:named_table, :public, :set, read_concurrency: true])
    :ok
  end

  def put(stream_id, snapshot), do: :ets.insert(@table, {stream_id, snapshot})

  def get(stream_id) do
    case :ets.lookup(@table, stream_id) do
      [{_, snap}] -> snap
      [] -> nil
    end
  end
end
