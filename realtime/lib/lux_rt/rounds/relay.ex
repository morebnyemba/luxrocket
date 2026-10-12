defmodule LuxRt.Rounds.Relay do
  @moduledoc """
  Journal relay (doc 06 §5.6): publishes unrelayed facts to Django in stream order, at least
  once, and marks them relayed only after Django acknowledges. Django de-duplicates.
  """

  use GenServer
  require Logger
  alias LuxRt.{Platform, Repo}

  @interval 100
  @batch 500

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Ask the relay to run now (called after a journal flush)."
  def poke do
    if pid = Process.whereis(__MODULE__), do: send(pid, :tick)
    :ok
  end

  @impl true
  def init(_opts) do
    schedule()
    {:ok, %{busy: false}}
  end

  @impl true
  def handle_info(:tick, state) do
    relay_all()
    schedule()
    {:noreply, state}
  end

  defp schedule, do: Process.send_after(self(), :tick, @interval)

  defp relay_all do
    case relay_batch() do
      :more -> relay_all()
      _ -> :ok
    end
  rescue
    e -> Logger.warning("journal relay failed: #{Exception.message(e)}")
  end

  defp relay_batch do
    %{rows: rows} =
      Repo.query!(
        """
        SELECT journal_id, stream_id, stream_seq, event_id::text, round_id::text, type, payload
          FROM rt.round_journal WHERE relayed_at IS NULL
         ORDER BY stream_id, stream_seq LIMIT $1
        """,
        [@batch]
      )

    if rows == [] do
      :idle
    else
      events =
        Enum.map(rows, fn [_id, stream, seq, eid, rid, type, payload] ->
          %{
            event_id: eid,
            stream_id: stream,
            stream_seq: seq,
            round_id: rid,
            type: type,
            payload: payload
          }
        end)

      case Application.get_env(:lux_rt, :platform_client, Platform).post_events(events) do
        :ok ->
          mark(Enum.map(rows, &hd/1))
          if length(rows) == @batch, do: :more, else: :idle

        {:gap, expected} ->
          # Django already has everything below `expected` for these streams.
          below = for [id, _s, seq | _] <- rows, seq < expected, do: id
          mark(below)
          Logger.warning("relay gap: Django expects seq #{expected}")
          :idle

        {:error, reason} ->
          Logger.debug("relay deferred: #{inspect(reason)}")
          :idle
      end
    end
  end

  defp mark([]), do: :ok

  defp mark(ids) do
    Repo.query!("UPDATE rt.round_journal SET relayed_at = now() WHERE journal_id = ANY($1)", [ids])
  end
end
