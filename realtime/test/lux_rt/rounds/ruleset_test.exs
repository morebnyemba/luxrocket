defmodule LuxRt.Rounds.RulesetTest do
  @moduledoc "Approved ruleset bindings are adopted only at a round boundary (doc 12 §3.3)."
  use LuxRt.DataCase, async: false

  alias LuxRt.Math.Outcome
  alias LuxRt.PlatformStub
  alias LuxRt.Rounds.Coordinator
  alias Phoenix.Socket.Broadcast

  @timing [
    betting_window_ms: 300,
    close_grace_ms: 150,
    crash_grace_ms: 20,
    cooldown_ms: 150,
    tick_ms: 50,
    journal_flush_ms: 2,
    lease_ttl_ms: 2_000,
    lease_renew_ms: 500
  ]

  setup do
    Ecto.Adapters.SQL.Sandbox.mode(LuxRt.Repo, {:shared, self()})
    previous = Application.get_env(:lux_rt, :timing)
    Application.put_env(:lux_rt, :timing, @timing)
    on_exit(fn -> Application.put_env(:lux_rt, :timing, previous) end)
    start_supervised!(PlatformStub)
    stream = "r#{System.unique_integer([:positive])}"
    LuxRtWeb.Endpoint.subscribe("stream:" <> stream)
    {:ok, stream: stream}
  end

  defp start(stream), do: start_supervised!({Coordinator, stream}, restart: :temporary)

  defp await(event, timeout \\ 6_000) do
    assert_receive %Broadcast{event: ^event, payload: payload}, timeout
    payload
  end

  defp created(stream) do
    %{rows: rows} =
      LuxRt.Repo.query!(
        "SELECT payload FROM rt.round_journal WHERE stream_id = $1 AND type = 'ROUND_CREATED' ORDER BY stream_seq",
        [stream]
      )

    List.flatten(rows)
  end

  defp config(version, edge, max \\ 100_000_000) do
    %{
      "stream" => "ignored",
      "version" => version,
      "ruleset" => %{
        "code" => "LR-TEST-#{edge}",
        "house_edge_bp" => edge,
        "max_multiplier_x10000" => max
      }
    }
  end

  test "a binding received mid-round applies from the next round only", %{stream: stream} do
    start(stream)
    await("ROUND_OPEN")
    Coordinator.set_rules(stream, config(2, 500))
    crashed = await("ROUND_CRASHED")
    seed = Base.decode16!(crashed.data.seed, case: :lower)
    salt = Base.decode16!(crashed.data.salt, case: :lower)
    # The round in flight kept the rules it was created with.
    assert Outcome.crash_from_seed(seed, salt, 300, 100_000_000) == crashed.data.crash_x10000

    await("ROUND_OPEN")
    [first, second | _] = created(stream)
    assert first["house_edge_bp"] == 300 and first["ruleset_version"] == 0
    assert second["house_edge_bp"] == 500
    assert second["ruleset_code"] == "LR-TEST-500" and second["ruleset_version"] == 2
  end

  test "stale or invalid bindings are refused", %{stream: stream} do
    start(stream)
    await("ROUND_OPEN")
    Coordinator.set_rules(stream, config(3, 400))
    Coordinator.set_rules(stream, config(2, 450))
    Coordinator.set_rules(stream, config(4, 0))
    Coordinator.set_rules(stream, config(5, 300, 200_000_000))
    state = :sys.get_state(Coordinator.via(stream)) |> elem(1)
    assert state.pending_rules.version == 3 and state.pending_rules.house_edge_bp == 400
  end

  test "boot takes the platform's current binding", %{stream: stream} do
    PlatformStub.set_stream_config(config(7, 350))
    start(stream)
    await("ROUND_OPEN")
    [first | _] = created(stream)
    assert first["house_edge_bp"] == 350 and first["ruleset_version"] == 7
  end

  test "boot without the platform falls back to the last journaled rules", %{stream: stream} do
    PlatformStub.set_stream_config(config(9, 250))
    pid = start(stream)
    await("ROUND_OPEN")
    stop_supervised!({Coordinator, stream})
    refute Process.alive?(pid)

    LuxRt.Repo.query!(
      "UPDATE rt.stream_lease SET expires_at = now() - interval '1 minute' WHERE stream_id = $1",
      [stream]
    )

    PlatformStub.set_stream_config(nil)
    start(stream)
    await("ROUND_OPEN")

    assert created(stream) |> List.last() |> Map.take(["house_edge_bp", "ruleset_version"]) ==
             %{"house_edge_bp" => 250, "ruleset_version" => 9}
  end
end
