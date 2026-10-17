defmodule LuxRt.Math.Multiplier do
  @moduledoc """
  Multiplier units and payout arithmetic (ADR-008, doc 07).

  All multipliers are integers in ten-thousandths: `10_000` is 1.00x. Crash points and
  auto cash-out targets lie on the 0.01x grid (multiples of `grid/0`); manual cash-outs are
  priced at full 0.0001x precision.
  """

  @unit 10_000
  @grid 100

  def unit, do: @unit
  def grid, do: @grid

  @doc "Payout in minor units: floor(stake * multiplier / unit), capped by max win."
  @spec payout_minor(pos_integer(), pos_integer(), non_neg_integer() | nil) :: non_neg_integer()
  def payout_minor(stake_minor, multiplier_x10000, max_win_minor \\ nil)
      when is_integer(stake_minor) and stake_minor > 0 and is_integer(multiplier_x10000) and
             multiplier_x10000 >= @unit do
    payout = div(stake_minor * multiplier_x10000, @unit)
    if is_integer(max_win_minor), do: min(payout, max_win_minor), else: payout
  end

  @doc "Effective auto cash-out target k_eff = min(target, max-win multiplier, max multiplier)."
  @spec effective_target(pos_integer() | nil, pos_integer(), pos_integer(), pos_integer()) ::
          pos_integer()
  def effective_target(auto_x10000, stake_minor, max_win_minor, max_multiplier_x10000) do
    cap_by_win = div(max_win_minor * @unit, stake_minor)

    [cap_by_win, max_multiplier_x10000, auto_x10000]
    |> Enum.reject(&is_nil/1)
    |> Enum.min()
    |> max(@unit)
  end
end
