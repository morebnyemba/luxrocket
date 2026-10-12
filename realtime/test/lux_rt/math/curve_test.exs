defmodule LuxRt.Math.CurveTest do
  use ExUnit.Case, async: true

  alias LuxRt.Math.Curve

  @vectors_path Path.expand("../../../../contracts/math/lr-crash-1/vectors.json", __DIR__)
  @external_resource @vectors_path
  @vectors @vectors_path |> File.read!() |> Jason.decode!()

  setup_all do
    p = @vectors["params"]
    {:ok, table: Curve.generate(p["curve_lambda_per_ms"], p["max_multiplier_x10000"])}
  end

  test "table is bit-identical to the Python reference", %{table: table} do
    p = @vectors["params"]
    assert Curve.length(table) == p["curve_length"]
    assert Curve.sha256(table) == p["curve_table_sha256"]
  end

  test "samples and crash times match", %{table: table} do
    for s <- @vectors["curve_samples"],
        do: assert(Curve.at(table, s["t_ms"]) == s["multiplier_x10000"])

    for c <- @vectors["crash_times"] do
      assert Curve.crossing_time(table, c["crash_x10000"]) == c["t_crash_ms"]
    end
  end

  test "manual cash-out before the crash never reaches the crash point", %{table: table} do
    for crash <- [10_100, 15_000, 20_000, 123_400, 1_000_000] do
      t_crash = Curve.crossing_time(table, crash)
      if t_crash > 0, do: assert(Curve.at(table, t_crash - 1) < crash)
    end
  end
end
