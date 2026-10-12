defmodule LuxRt.Math.OutcomeTest do
  use ExUnit.Case, async: true

  alias LuxRt.Math.{Multiplier, Outcome}

  @vectors_path Path.expand("../../../../contracts/math/lr-crash-1/vectors.json", __DIR__)
  @external_resource @vectors_path
  @vectors @vectors_path |> File.read!() |> Jason.decode!()
  @edge @vectors["params"]["house_edge_bp"]
  @max @vectors["params"]["max_multiplier_x10000"]

  defp hex!(s), do: Base.decode16!(s, case: :lower)

  test "matches r vectors from the Python reference" do
    for %{"r" => r, "crash_x10000" => crash} <- @vectors["r_vectors"] do
      assert Outcome.crash_from_r(String.to_integer(r), @edge, @max) == crash
    end
  end

  test "matches seed vectors from the Python reference" do
    salt = hex!(@vectors["salt"])

    for v <- @vectors["seed_vectors"] do
      seed = hex!(v["seed"])
      hash = Outcome.round_hash(seed, salt)
      assert Base.encode16(hash, case: :lower) == v["round_hash"]
      assert Outcome.first_52_bits(hash) == String.to_integer(v["r"])
      assert Outcome.crash_from_seed(seed, salt, @edge, @max) == v["crash_x10000"]
    end
  end

  test "verifies chain commitments" do
    chain = Enum.map(@vectors["chain"], &hex!/1)

    for [earlier, later] <- Enum.chunk_every(chain, 2, 1, :discard) do
      assert Outcome.verify_commitment(earlier, later)
    end

    refute Outcome.verify_commitment(Enum.at(chain, 0), Enum.at(chain, 2))
  end

  test "matches payout vectors" do
    for v <- @vectors["payouts"] do
      assert Multiplier.payout_minor(v["stake_minor"], v["multiplier_x10000"], v["max_win_minor"]) ==
               v["payout_minor"]
    end
  end

  test "crash points are on the 0.01x grid and bounded" do
    for _ <- 1..2_000 do
      c = Outcome.crash_from_r(:rand.uniform(Bitwise.bsl(1, 52)) - 1, @edge, @max)
      assert rem(c, 100) == 0
      assert c >= 10_000 and c <= @max
    end
  end

  test "effective target caps exposure by max win" do
    assert Multiplier.effective_target(nil, 1_000, 10_000, 100_000_000) == 100_000
    assert Multiplier.effective_target(50_000, 1_000, 10_000, 100_000_000) == 50_000
  end
end
