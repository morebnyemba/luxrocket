defmodule LuxRtWeb.UserSocket do
  @moduledoc """
  Player WebSocket (doc 10 §1-§2). Authenticated with a single-use, 30-second WS ticket that is
  consumed via the Django internal API; long-lived session tokens never appear in the URL.
  """
  use Phoenix.Socket

  channel "stream:*", LuxRtWeb.GameChannel

  @impl true
  def connect(%{"ticket" => ticket}, socket, _connect_info)
      when is_binary(ticket) and ticket != "" do
    case Application.get_env(:lux_rt, :platform_client, LuxRt.Platform).consume_ticket(ticket) do
      {:ok, session} -> {:ok, assign(socket, :session, session)}
      _ -> :error
    end
  end

  def connect(_params, _socket, _connect_info), do: :error

  # Lets the platform disconnect every socket of a revoked session.
  @impl true
  def id(socket), do: "session:" <> socket.assigns.session["session_id"]
end
