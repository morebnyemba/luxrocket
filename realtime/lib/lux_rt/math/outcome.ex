defmodule LuxRt.Math.Outcome do
  @moduledoc """
  Provably-fair outcome generation, formula LR-CRASH-1 (doc 07 §2, §6).

  Exact integer arithmetic. Must agree bit-for-bit with the Python reference implementation;
  see `contracts/math/lr-crash-1/vectors.json`.
  """

  alias LuxRt.Math.Multiplier

  @d Bitwise.bsl(1, 52)

  def formula_version, do: "LR-CRASH-1"

  @doc "Integer value of the first 52 bits of a digest (big-endian)."
  @spec first_52_bits(binary()) :: non_neg_integer()
  def first_52_bits(<<r::unsigned-big-integer-size(52), _rest::bitstring>>), do: r

  @doc """
  Crash point in ten-thousandths for a 52-bit uniform integer `r`:
  `100 * clamp(floor(100 * (10000 - e_bp) * D / (10000 * (D - r))), 100, M / 100)`.
  """
  @spec crash_from_r(non_neg_integer(), non_neg_integer(), pos_integer()) :: pos_integer()
  def crash_from_r(r, house_edge_bp, max_multiplier_x10000)
      when is_integer(r) and r >= 0 and r < @d and house_edge_bp in 0..9_999 and
             rem(max_multiplier_x10000, 100) == 0 and max_multiplier_x10000 >= 10_100 do
    grid = Multiplier.grid()
    raw = div(100 * (10_000 - house_edge_bp) * @d, 10_000 * (@d - r))
    raw |> max(100) |> min(div(max_multiplier_x10000, grid)) |> Kernel.*(grid)
  end

  @spec round_hash(binary(), binary()) :: binary()
  def round_hash(seed, salt), do: :crypto.mac(:hmac, :sha256, seed, salt)

  @spec crash_from_seed(binary(), binary(), non_neg_integer(), pos_integer()) :: pos_integer()
  def crash_from_seed(seed, salt, house_edge_bp, max_multiplier_x10000) do
    seed
    |> round_hash(salt)
    |> first_52_bits()
    |> crash_from_r(house_edge_bp, max_multiplier_x10000)
  end

  @doc "s_{i+1} = SHA256(s_i). Rounds consume the chain in reverse order."
  @spec chain_next(binary()) :: binary()
  def chain_next(seed), do: :crypto.hash(:sha256, seed)

  @doc "A round's commitment is the previous round's revealed seed (or the chain terminal)."
  @spec verify_commitment(binary(), binary()) :: boolean()
  def verify_commitment(revealed, commitment),
    do: :crypto.hash_equals(chain_next(revealed), commitment)
end
