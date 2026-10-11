defmodule LuxRtWeb.Router do
  use LuxRtWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", LuxRtWeb do
    pipe_through :api
    get "/healthz", HealthController, :show
    post "/internal/v1/platform-events", InternalController, :platform_events
  end
end
