defmodule LuxRt.Math.Curve do
  @moduledoc """
  Tabulated multiplier curve (doc 07 §3): `curve[t] = floor(10000 * exp(lambda * t))`, t in ms.

  Computed with exact big-integer fixed-point arithmetic so the table is bit-identical to the
  Python reference (checked against `curve_table_sha256` in the shared vectors). The table is
  an int32 little-endian binary held in `:persistent_term` for O(1) lookups.
  """

  import Bitwise

  # Fixed-point scale: 10^90 leaves ~80 guard digits after 153k multiplications.
  @scale Integer.pow(10, 90)

  @doc "Builds the table up to the first t with curve[t] >= max_multiplier_x10000."
  @spec generate(String.t(), pos_integer()) :: binary()
  def generate(lambda_per_ms, max_multiplier_x10000) do
    {num, den} = parse_decimal(lambda_per_ms)
    base = exp_fixed(num, den)
    do_generate(@scale, base, max_multiplier_x10000, [])
  end

  defp do_generate(value, base, max, acc) do
    v = div(value * 10_000, @scale)
    acc = [<<v::little-signed-32>> | acc]

    if v >= max do
      acc |> Enum.reverse() |> IO.iodata_to_binary()
    else
      do_generate(div(value * base, @scale), base, max, acc)
    end
  end

  # e^(num/den) in fixed point via its Taylor series (exact to the last few ulps).
  defp exp_fixed(num, den), do: exp_terms(@scale, @scale, num, den, 1)

  defp exp_terms(sum, term, num, den, k) do
    next = div(term * num, den * k)
    if next == 0, do: sum, else: exp_terms(sum + next, next, num, den, k + 1)
  end

  @doc false
  def parse_decimal(str) do
    case String.split(str, ".") do
      [int] ->
        {String.to_integer(int), 1}

      [int, frac] ->
        den = Integer.pow(10, byte_size(frac))
        {String.to_integer(int) * den + String.to_integer(frac), den}
    end
  end

  @spec sha256(binary()) :: String.t()
  def sha256(table), do: :crypto.hash(:sha256, table) |> Base.encode16(case: :lower)

  @doc "Number of entries in the table."
  def length(table), do: byte_size(table) >>> 2

  @doc "Multiplier (x10000) at `t` ms after launch. Clamped to the last entry."
  @spec at(binary(), integer()) :: pos_integer()
  def at(table, t) when t <= 0, do: value(table, 0)

  def at(table, t) do
    last = __MODULE__.length(table) - 1
    value(table, min(t, last))
  end

  defp value(table, i) do
    <<v::little-signed-32>> = binary_part(table, i * 4, 4)
    v
  end

  @doc "Smallest t with curve[t] >= target (crash time and auto cash-out crossing time)."
  @spec crossing_time(binary(), pos_integer()) :: non_neg_integer()
  def crossing_time(table, target) do
    search(table, target, 0, __MODULE__.length(table))
  end

  defp search(_table, _target, lo, hi) when lo >= hi, do: lo

  defp search(table, target, lo, hi) do
    mid = div(lo + hi, 2)

    if value(table, mid) < target,
      do: search(table, target, mid + 1, hi),
      else: search(table, target, lo, mid)
  end

  # ---- process-wide default table ----------------------------------------------------------

  @key {__MODULE__, :default}

  @doc "Loads (or returns) the table for the configured ruleset."
  def default do
    case :persistent_term.get(@key, nil) do
      nil ->
        rules = Application.fetch_env!(:lux_rt, :ruleset)
        table = generate(rules[:curve_lambda_per_ms], rules[:max_multiplier_x10000])
        :persistent_term.put(@key, table)
        table

      table ->
        table
    end
  end
end
