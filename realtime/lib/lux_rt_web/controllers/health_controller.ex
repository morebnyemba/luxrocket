defmodule LuxRtWeb.HealthController do
  use LuxRtWeb, :controller

  @doc "Liveness + database reachability. Contains no sensitive detail."
  def show(conn, _params) do
    db_ok =
      case Ecto.Adapters.SQL.query(LuxRt.Repo, "SELECT 1", []) do
        {:ok, _} -> true
        _ -> false
      end

    conn
    |> put_status(if db_ok, do: 200, else: 503)
    |> json(%{status: if(db_ok, do: "ok", else: "degraded"), db: db_ok})
  end
end
