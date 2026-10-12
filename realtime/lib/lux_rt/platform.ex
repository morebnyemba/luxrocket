defmodule LuxRt.Platform do
  @moduledoc "Client for the Django internal API (doc 06 §8). Authenticated with the service token."

  require Logger

  defp cfg, do: Application.fetch_env!(:lux_rt, :platform)

  defp req(timeout_ms) do
    Req.new(
      base_url: cfg()[:base_url],
      auth: {:bearer, cfg()[:service_token]},
      receive_timeout: timeout_ms,
      connect_options: [timeout: min(timeout_ms, 1_000)],
      retry: false
    )
  end

  @doc "Consume a single-use WS ticket. Returns the session view or an error."
  def consume_ticket(ticket) do
    case Req.post(req(1_000), url: "/internal/v1/ws-tickets/consume", json: %{ticket: ticket}) do
      {:ok, %{status: 200, body: %{"session" => session}}} -> {:ok, session}
      {:ok, %{status: status}} -> {:error, status}
      {:error, reason} -> {:error, reason}
    end
  end

  @doc """
  Place a bet: Django validates, debits the wallet and answers ACCEPTED / REJECTED / UNKNOWN.
  No retries — the call is deadline-bound; any failure is an UNKNOWN outcome.
  """
  def place_bet(body, timeout_ms) do
    case Req.post(req(timeout_ms), url: "/internal/v1/bets", json: body) do
      {:ok, %{status: 200, body: %{"status" => _} = result}} ->
        result

      {:ok, %{status: status}} ->
        %{"status" => "UNKNOWN", "code" => "HTTP_#{status}"}

      {:error, reason} ->
        %{"status" => "UNKNOWN", "code" => "TRANSPORT", "reason" => inspect(reason)}
    end
  end

  @doc "The stream's approved ruleset as currently bound by the platform (boot-time sync)."
  def stream_config(stream) do
    case Req.get(req(2_000), url: "/internal/v1/streams/#{URI.encode(stream)}/config") do
      {:ok, %{status: 200, body: %{"version" => _} = config}} -> {:ok, config}
      {:ok, %{status: status}} -> {:error, status}
      {:error, reason} -> {:error, reason}
    end
  end

  @doc "Relay a batch of journal facts. Returns :ok, {:gap, expected_seq} or {:error, reason}."
  def post_events(events) do
    case Req.post(req(5_000), url: "/internal/v1/rt-events", json: %{events: events}) do
      {:ok, %{status: 200}} -> :ok
      {:ok, %{status: 409, body: %{"expected_seq" => seq}}} -> {:gap, seq}
      {:ok, %{status: status}} -> {:error, status}
      {:error, reason} -> {:error, reason}
    end
  end
end
