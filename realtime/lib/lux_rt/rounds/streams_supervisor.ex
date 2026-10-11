defmodule LuxRt.Rounds.StreamsSupervisor do
  @moduledoc "One coordinator per configured stream (doc 06 §2)."
  use Supervisor

  def start_link(streams), do: Supervisor.start_link(__MODULE__, streams, name: __MODULE__)

  @impl true
  def init(streams) do
    children = Enum.map(streams, &LuxRt.Rounds.Coordinator.child_spec/1)
    # Generous restart intensity: a lease loss restarts the coordinator, which then voids.
    Supervisor.init(children, strategy: :one_for_one, max_restarts: 20, max_seconds: 60)
  end
end
