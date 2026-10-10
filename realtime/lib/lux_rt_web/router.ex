defmodule LuxRtWeb.Router do
  use LuxRtWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", LuxRtWeb do
    pipe_through :api
    get "/healthz", HealthController, :show
  end
end
