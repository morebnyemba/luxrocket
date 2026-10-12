defmodule LuxRt.Tables do
  @moduledoc """
  Owns node-local ETS tables so they outlive request and coordinator processes:
  the public round snapshot cache and the platform-event de-duplication set (pruned).
  """
  use GenServer

  @seen :lux_rt_seen_platform_events
  @seen_ttl_ms 10 * 60 * 1000
  @prune_every_ms 60 * 1000

  def start_link(_), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  @doc "Records an event id; true if it was not seen before."
  def first_time?(event_id),
    do: :ets.insert_new(@seen, {event_id, System.monotonic_time(:millisecond)})

  @impl true
  def init(nil) do
    :ets.new(@seen, [:named_table, :public, :set, write_concurrency: true])
    LuxRt.Rounds.Snapshot.init()
    Process.send_after(self(), :prune, @prune_every_ms)
    {:ok, nil}
  end

  @impl true
  def handle_info(:prune, state) do
    cutoff = System.monotonic_time(:millisecond) - @seen_ttl_ms
    :ets.select_delete(@seen, [{{:_, :"$1"}, [{:<, :"$1", cutoff}], [true]}])
    Process.send_after(self(), :prune, @prune_every_ms)
    {:noreply, state}
  end
end
