defmodule LuxRt.Application do
  # See https://hexdocs.pm/elixir/Application.html
  # for more information on OTP Applications
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children =
      [
        LuxRtWeb.Telemetry,
        LuxRt.Repo,
        {DNSCluster, query: Application.get_env(:lux_rt, :dns_cluster_query) || :ignore},
        {Phoenix.PubSub, name: LuxRt.PubSub},
        LuxRt.Tables,
        {Registry, keys: :unique, name: LuxRt.CoordinatorRegistry},
        {Task.Supervisor, name: LuxRt.TaskSupervisor},
        {LuxRt.Rounds.StreamsSupervisor, streams()}
      ] ++
        relay() ++
        [
          LuxRtWeb.Endpoint
        ]

    # See https://hexdocs.pm/elixir/Supervisor.html
    # for other strategies and supported options
    opts = [strategy: :one_for_one, name: LuxRt.Supervisor]
    Supervisor.start_link(children, opts)
  end

  defp relay do
    if Application.get_env(:lux_rt, :start_relay, true), do: [LuxRt.Rounds.Relay], else: []
  end

  defp streams do
    if Application.get_env(:lux_rt, :start_coordinators, true),
      do: Application.fetch_env!(:lux_rt, :streams),
      else: []
  end

  # Tell Phoenix to update the endpoint configuration
  # whenever the application is updated.
  @impl true
  def config_change(changed, _new, removed) do
    LuxRtWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
