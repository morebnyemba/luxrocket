defmodule LuxRt.PlatformStub do
  @moduledoc "Test double for the Django internal API. Behaviour is set per test via an Agent."
  use Agent

  def start_link(_),
    do: Agent.start_link(fn -> %{bet: &default_bet/1, events: []} end, name: __MODULE__)

  def set_bet(fun), do: Agent.update(__MODULE__, &Map.put(&1, :bet, fun))
  def events, do: Agent.get(__MODULE__, & &1.events)

  def place_bet(body, _timeout) do
    fun = Agent.get(__MODULE__, & &1.bet)
    fun.(body)
  end

  def post_events(events) do
    Agent.update(__MODULE__, &Map.update!(&1, :events, fn e -> e ++ events end))
    :ok
  end

  def set_stream_config(config),
    do: Agent.update(__MODULE__, &Map.put(&1, :stream_config, config))

  def stream_config(_stream) do
    case Agent.get(__MODULE__, &Map.get(&1, :stream_config)) do
      nil -> {:error, :unavailable}
      config -> {:ok, config}
    end
  end

  def consume_ticket("good-ticket"), do: {:ok, session("ses_test", "global")}
  def consume_ticket(_), do: {:error, 401}

  def session(id, stream) do
    %{
      "session_id" => id,
      "stream_id" => stream,
      "currency" => "USD",
      "panels" => 2,
      "limits" => %{"min_stake" => "10", "max_stake" => "10000", "max_win" => "1000000"}
    }
  end

  def default_bet(body) do
    %{
      "status" => "ACCEPTED",
      "bet_id" => "bet_" <> String.slice(body.command_id, 0, 8),
      "stake" => body.stake,
      "max_win" => "1000000",
      "balance" => "99500"
    }
  end
end
