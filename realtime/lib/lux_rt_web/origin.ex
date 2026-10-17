defmodule LuxRtWeb.Origin do
  @moduledoc "WebSocket origin check: exactly the configured game origins (doc 11 §1)."

  def allowed?(%URI{} = uri) do
    origin = "#{uri.scheme}://#{uri.host}" <> port_suffix(uri)
    origin in Application.get_env(:lux_rt, :game_origins, ["http://localhost:3000"])
  end

  defp port_suffix(%URI{scheme: "http", port: 80}), do: ""
  defp port_suffix(%URI{scheme: "https", port: 443}), do: ""
  defp port_suffix(%URI{port: nil}), do: ""
  defp port_suffix(%URI{port: port}), do: ":#{port}"
end
