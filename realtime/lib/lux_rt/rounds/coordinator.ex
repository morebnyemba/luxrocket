defmodule LuxRt.Rounds.Coordinator do
  @moduledoc """
  The single authoritative coordinator for one round stream (doc 06 §4-§7).

  It owns round time: betting cut-off, bet admission, launch, manual and auto cash-outs, the
  crash and voids. Every decision is appended to the fenced journal *before* any player is told
  about it, so a crash of this process can never leave an acknowledged but unrecorded fact.

  States: `:booting -> :betting_open -> :betting_closed -> :flying -> :cooldown -> ...`.
  On (re)start, an interrupted round is voided (ADR-005) before a new one is created.
  """

  @behaviour :gen_statem
  require Logger

  alias LuxRt.Fairness.SeedChain
  alias LuxRt.Math.{Curve, Multiplier, Outcome}
  alias LuxRt.Platform
  alias LuxRt.Repo
  alias LuxRt.Rounds.{Journal, Lease, Relay, Snapshot}

  @unit 10_000

  defstruct [
    :stream,
    :holder,
    :token,
    :chain,
    :table,
    :rules,
    :pending_rules,
    :timing,
    :round,
    seq: 0,
    pub_seq: 0,
    tick_seq: 0,
    bets: %{},
    pending: %{},
    excluded: %{},
    tasks: %{},
    auto_queue: [],
    buf: [],
    flush_scheduled: false,
    recent: []
  ]

  # ---- public API --------------------------------------------------------------------------

  def child_spec(stream) do
    %{
      id: {__MODULE__, stream},
      start: {__MODULE__, :start_link, [stream]},
      restart: :permanent,
      shutdown: 5_000
    }
  end

  def start_link(stream), do: :gen_statem.start_link(via(stream), __MODULE__, stream, [])

  def via(stream), do: {:via, Registry, {LuxRt.CoordinatorRegistry, stream}}

  @doc "Forward a stamped PLACE_BET command. Results arrive as private events."
  def place_bet(stream, cmd), do: :gen_statem.cast(via(stream), {:place_bet, cmd})

  @doc "Forward a stamped CASH_OUT command. Results arrive as private events."
  def cash_out(stream, cmd), do: :gen_statem.cast(via(stream), {:cash_out, cmd})

  @doc """
  A ruleset binding approved on the platform. It never changes the current round: the
  coordinator keeps it pending and adopts it when it creates the next round (doc 12 §3.3).
  """
  def set_rules(stream, config) when is_binary(stream) do
    case Registry.lookup(LuxRt.CoordinatorRegistry, stream) do
      [] -> :ok
      _ -> :gen_statem.cast(via(stream), {:set_rules, config})
    end
  end

  def set_rules(_stream, _config), do: :ok

  @doc "The calling player's bets in the current round (for snapshots/resync)."
  def player_view(stream, session_id) do
    :gen_statem.call(via(stream), {:player_view, session_id}, 200)
  catch
    :exit, _ -> []
  end

  # ---- gen_statem --------------------------------------------------------------------------

  @impl true
  def callback_mode, do: [:handle_event_function, :state_enter]

  @impl true
  def init(stream) do
    data = %__MODULE__{
      stream: stream,
      holder: "#{node()}/#{System.unique_integer([:positive])}",
      rules: default_rules(),
      timing: Map.new(Application.fetch_env!(:lux_rt, :timing)),
      table: Curve.default()
    }

    {:ok, :booting, data}
  end

  @impl true
  # --- booting: acquire the lease, recover, create the first round ---
  def handle_event(:enter, _old, :booting, _data),
    do: {:keep_state_and_data, [{:state_timeout, 0, :boot}]}

  def handle_event(:state_timeout, :boot, :booting, data) do
    case Lease.acquire(data.stream, data.holder, data.timing.lease_ttl_ms) do
      {:ok, token} ->
        data = %{data | token: token, chain: SeedChain.load_or_create(data.stream)}
        data = data |> recover() |> load_rules()
        Logger.info("coordinator for #{data.stream} active (fencing token #{token})")
        data = create_round(data, now())
        {:next_state, :betting_open, data, [renew_timer(data)]}

      :taken ->
        {:keep_state_and_data, [{:state_timeout, 1_000, :boot}]}
    end
  end

  # --- betting open ---
  def handle_event(:enter, _old, :betting_open, data) do
    r = data.round

    data =
      journal(data, "ROUND_OPENED", %{
        opens_at: r.opens_at,
        close_at: r.close_at,
        launch_at: r.launch_at
      })

    data = flush!(data)
    update_round(data, "BETTING_OPEN")

    data =
      broadcast(data, "ROUND_OPEN", %{
        number: r.number,
        opens_at: r.opens_at,
        close_at: r.close_at,
        launch_at: r.launch_at,
        commitment: r.commitment,
        curve: curve_info(data)
      })

    {:keep_state, publish_snapshot(data, "BETTING_OPEN"),
     [{:state_timeout, max(r.close_at - now(), 0), :close}]}
  end

  def handle_event(:state_timeout, :close, :betting_open, data),
    do: {:next_state, :betting_closed, data}

  # --- betting closed (awaiting in-flight debits until launch) ---
  def handle_event(:enter, _old, :betting_closed, data) do
    data = data |> journal("BETTING_CLOSED", %{}) |> flush!()
    update_round(data, "BETTING_CLOSED")
    r = data.round
    data = broadcast(data, "BETTING_CLOSED", %{close_at: r.close_at, launch_at: r.launch_at})

    {:keep_state, publish_snapshot(data, "BETTING_CLOSED"),
     [{:state_timeout, max(r.launch_at - now(), 0), :launch}]}
  end

  def handle_event(:state_timeout, :launch, :betting_closed, data),
    do: {:next_state, :flying, data}

  # --- flying ---
  def handle_event(:enter, _old, :flying, data) do
    r = data.round

    # Bets whose debit has not been confirmed by launch are excluded (refunded by Django).
    {data, excluded} =
      Enum.reduce(data.pending, {data, %{}}, fn {key, p}, {d, ex} ->
        d =
          journal(d, "BET_EXCLUDED", %{
            session_id: p.session_id,
            command_id: p.command_id,
            reason: "PENDING_AT_LAUNCH"
          })

        {d, Map.put(ex, key, p)}
      end)

    data = %{data | pending: %{}, excluded: excluded}
    data = data |> journal("ROUND_LAUNCHED", %{launch_at: r.launch_at}) |> flush!()
    update_round(data, "FLYING")

    data = %{data | auto_queue: build_auto_queue(data), tick_seq: 0}
    data = broadcast(data, "ROCKET_LAUNCHED", %{launch_at: r.launch_at, curve: curve_info(data)})
    data = publish_snapshot(data, "FLYING")

    crash_in = max(r.crash_at + data.timing.crash_grace_ms - now(), 0)

    actions =
      [
        {{:timeout, :crash}, crash_in, :crash},
        {{:timeout, :tick}, data.timing.tick_ms, :tick}
      ] ++ auto_timer(data)

    {:keep_state, data, actions}
  end

  def handle_event({:timeout, :tick}, :tick, :flying, data) do
    r = data.round
    elapsed = now() - r.launch_at

    if elapsed < r.t_crash do
      data = %{data | tick_seq: data.tick_seq + 1}

      LuxRtWeb.Endpoint.broadcast("stream:" <> data.stream, "MULTIPLIER_UPDATE", %{
        type: "MULTIPLIER_UPDATE",
        v: 1,
        stream_id: data.stream,
        round_id: r.id,
        server_ts: now(),
        data: %{
          tick_seq: data.tick_seq,
          elapsed_ms: elapsed,
          multiplier_x10000: Curve.at(data.table, elapsed)
        }
      })

      {:keep_state, data, [{{:timeout, :tick}, data.timing.tick_ms, :tick}]}
    else
      :keep_state_and_data
    end
  end

  def handle_event({:timeout, :auto}, :auto, :flying, data) do
    data = run_auto_cashouts(data, now() - data.round.launch_at)
    {:keep_state, schedule_flush(data), auto_timer(data)}
  end

  def handle_event({:timeout, :crash}, :crash, :flying, data) do
    {:next_state, :cooldown, finish_crash(data)}
  end

  # --- cooldown, then the next round ---
  def handle_event(:enter, _old, :cooldown, data) do
    {:keep_state_and_data, [{:state_timeout, data.timing.cooldown_ms, :next_round}]}
  end

  def handle_event(:state_timeout, :next_round, :cooldown, data) do
    {:next_state, :betting_open, create_round(data, now())}
  end

  # ---- commands ----------------------------------------------------------------------------

  def handle_event(:cast, {:place_bet, cmd}, state, data) do
    {:keep_state, handle_place_bet(cmd, state, data)}
  end

  def handle_event(:cast, {:cash_out, cmd}, state, data) do
    {:keep_state, handle_cash_out(cmd, state, data)}
  end

  def handle_event(:cast, {:set_rules, config}, _state, data) do
    case parse_rules(config, data.table) do
      {:ok, rules} ->
        newest = max(data.rules.version, (data.pending_rules || %{version: 0}).version)

        if rules.version > newest do
          Logger.info(
            "#{data.stream}: ruleset #{rules.code} v#{rules.version} pending for next round"
          )

          {:keep_state, %{data | pending_rules: rules}}
        else
          :keep_state_and_data
        end

      {:error, why} ->
        Logger.error("#{data.stream}: refusing ruleset #{inspect(config)}: #{why}")
        :keep_state_and_data
    end
  end

  def handle_event({:call, from}, {:player_view, session_id}, _state, data) do
    {:keep_state_and_data, [{:reply, from, player_bets(data, session_id)}]}
  end

  # Django bet results (from supervised tasks).
  def handle_event(:info, {ref, result}, state, data) when is_reference(ref) do
    Process.demonitor(ref, [:flush])
    {:keep_state, handle_bet_result(ref, result, state, data)}
  end

  def handle_event(:info, {:DOWN, ref, :process, _pid, _reason}, state, data) do
    {:keep_state,
     handle_bet_result(ref, %{"status" => "UNKNOWN", "code" => "TASK_DOWN"}, state, data)}
  end

  # ---- background timers -------------------------------------------------------------------

  def handle_event(:info, :flush_now, _state, data) do
    {:keep_state, flush!(%{data | flush_scheduled: false})}
  end

  def handle_event({:timeout, :renew}, :renew, _state, data) do
    case safe_renew(data) do
      :ok ->
        {:keep_state_and_data, [renew_timer(data)]}

      :lost ->
        Logger.error("lease lost for #{data.stream}; halting (round will be voided on recovery)")
        {:stop, :lease_lost}
    end
  end

  def handle_event(:enter, _old, _state, _data), do: :keep_state_and_data

  def handle_event(_type, _msg, _state, _data), do: :keep_state_and_data

  # ---- rounds ------------------------------------------------------------------------------

  defp recover(data) do
    seq = Journal.last_seq(data.stream)
    data = %{data | seq: seq}

    %{rows: rows} =
      Repo.query!(
        """
        SELECT round_id::text, number, chain_id::text, chain_index, state FROM rt.round
         WHERE stream_id = $1 ORDER BY number DESC LIMIT 1
        """,
        [data.stream]
      )

    %{rows: recent} =
      Repo.query!(
        "SELECT crash_x10000 FROM rt.round WHERE stream_id = $1 AND state = 'CRASHED' ORDER BY number DESC LIMIT 30",
        [data.stream]
      )

    data = %{data | recent: List.flatten(recent)}

    case rows do
      [] ->
        Map.put(data, :next, %{number: 1, chain_index: 1})

      [[round_id, number, chain_id, chain_index, state]] ->
        data =
          if state in ["CRASHED", "VOIDED"] do
            data
          else
            void_interrupted(data, round_id, chain_id, chain_index)
          end

        next_index = if chain_id == data.chain.chain_id, do: chain_index + 1, else: 1
        Map.put(data, :next, %{number: number + 1, chain_index: next_index})
    end
  end

  defp void_interrupted(data, round_id, chain_id, chain_index) do
    seed =
      if chain_id == data.chain.chain_id,
        do: data.chain |> SeedChain.round_seed(chain_index) |> hex(),
        else: ""

    Logger.warning("voiding interrupted round #{round_id} (coordinator failover)")
    data = %{data | round: %{id: round_id}}

    data =
      data |> journal("ROUND_VOIDED", %{reason: "COORDINATOR_FAILOVER", seed: seed}) |> flush!()

    fenced!(
      data,
      "UPDATE rt.round SET state = 'VOIDED', seed_hex = $4, updated_at = now() WHERE round_id = $3::text::uuid",
      [
        round_id,
        seed
      ]
    )

    broadcast(data, "ROUND_VOIDED", %{reason: "COORDINATOR_FAILOVER", seed: seed})
  end

  defp create_round(data, opens_at) do
    data = adopt_pending_rules(data)
    %{number: number, chain_index: k} = data.next
    chain = data.chain
    seed = SeedChain.round_seed(chain, k)
    commitment = SeedChain.round_commitment(chain, k) |> hex()

    crash =
      Outcome.crash_from_seed(
        seed,
        chain.salt,
        data.rules.house_edge_bp,
        data.rules.max_multiplier_x10000
      )

    t_crash = Curve.crossing_time(data.table, crash)
    close_at = opens_at + data.timing.betting_window_ms
    launch_at = close_at + data.timing.close_grace_ms

    round = %{
      id: Ecto.UUID.generate(),
      number: number,
      chain_index: k,
      seed: seed,
      commitment: commitment,
      crash: crash,
      t_crash: t_crash,
      opens_at: opens_at,
      close_at: close_at,
      launch_at: launch_at,
      crash_at: launch_at + t_crash
    }

    fenced!(
      data,
      """
      INSERT INTO rt.round (round_id, stream_id, number, chain_id, chain_index, state, commitment,
                            opens_at, close_at, launch_at, fencing_token, inserted_at, updated_at)
      SELECT $3::text::uuid, $1, $4, $5::text::uuid, $6, 'PENDING', $7, $8, $9, $10, l.fencing_token, now(), now()
        FROM rt.stream_lease l WHERE l.stream_id = $1 AND l.holder = $2 AND l.fencing_token = $11
      """,
      [
        round.id,
        number,
        chain.chain_id,
        k,
        commitment,
        opens_at,
        close_at,
        launch_at,
        data.token
      ],
      raw: true
    )

    data = %{data | round: round, bets: %{}, pending: %{}, excluded: %{}, auto_queue: []}
    data = Map.put(data, :next, %{number: number + 1, chain_index: k + 1})

    journal(data, "ROUND_CREATED", %{
      number: number,
      commitment: commitment,
      chain_id: chain.chain_id,
      chain_index: k,
      house_edge_bp: data.rules.house_edge_bp,
      max_multiplier_x10000: data.rules.max_multiplier_x10000,
      ruleset_code: data.rules.code,
      ruleset_version: data.rules.version
    })
  end

  # ---- rulesets ------------------------------------------------------------------------------

  # Static, deployment-level game parameters (panels, curve, ...). A ruleset only overrides
  # code, version, house edge and max multiplier on top of these.
  defp static_rules, do: Map.new(Application.fetch_env!(:lux_rt, :ruleset))

  defp default_rules do
    r = static_rules()
    Map.merge(r, %{code: Map.get(r, :code, "LR-STD-97"), version: 0})
  end

  defp adopt_pending_rules(%{pending_rules: nil} = data), do: data

  defp adopt_pending_rules(%{pending_rules: rules} = data) do
    Logger.info(
      "#{data.stream}: adopting ruleset #{rules.code} v#{rules.version} at round boundary"
    )

    %{data | rules: rules, pending_rules: nil}
  end

  # Boot order: the platform's current binding; else the rules the last round was journaled with;
  # else the static default. The coordinator never invents rules.
  defp load_rules(data) do
    with {:ok, config} <- platform_client().stream_config(data.stream),
         {:ok, rules} <- parse_rules(config, data.table) do
      %{data | rules: rules}
    else
      _ ->
        case last_journaled_rules(data.stream) do
          {:ok, rules} ->
            Logger.warning("#{data.stream}: platform unreachable; using last journaled ruleset")
            %{data | rules: rules}

          :none ->
            data
        end
    end
  end

  defp last_journaled_rules(stream) do
    %{rows: rows} =
      Repo.query!(
        """
        SELECT payload FROM rt.round_journal
         WHERE stream_id = $1 AND type = 'ROUND_CREATED' ORDER BY stream_seq DESC LIMIT 1
        """,
        [stream]
      )

    with [[payload]] <- rows,
         {:ok, rules} <-
           parse_rules(
             %{
               "version" => payload["ruleset_version"] || 0,
               "ruleset" => %{
                 "code" => payload["ruleset_code"] || "LR-STD-97",
                 "house_edge_bp" => payload["house_edge_bp"],
                 "max_multiplier_x10000" => payload["max_multiplier_x10000"]
               }
             },
             nil
           ) do
      {:ok, rules}
    else
      _ -> :none
    end
  end

  @doc false
  def parse_rules(%{"version" => v, "ruleset" => r}, table) when is_integer(v) and is_map(r) do
    edge = r["house_edge_bp"]
    max = r["max_multiplier_x10000"]
    code = r["code"]
    ceiling = if table, do: Curve.at(table, Curve.length(table) - 1), else: max

    cond do
      not (is_binary(code) and code != "") ->
        {:error, "missing code"}

      not (is_integer(edge) and edge > 0 and edge < 10_000) ->
        {:error, "house edge out of range"}

      not (is_integer(max) and rem(max, 100) == 0 and max >= 10_100) ->
        {:error, "bad max multiplier"}

      max > ceiling ->
        {:error, "max multiplier beyond the curve table"}

      true ->
        {:ok, %{code: code, version: v, house_edge_bp: edge, max_multiplier_x10000: max}}
    end
  end

  def parse_rules(_config, _table), do: {:error, "malformed"}

  defp finish_crash(data) do
    r = data.round
    max = data.rules.max_multiplier_x10000

    {data, end_reason} =
      if r.crash >= max do
        # Journey complete: every still-active bet is cashed at the maximum (doc 07 §4).
        data =
          data.bets
          |> Enum.filter(fn {_k, b} -> b.status == :active end)
          |> Enum.reduce(data, fn {key, _b}, d ->
            accept_cashout(d, key, max, "MAX_MULTIPLIER", r.crash_at)
          end)

        {data, "MAX_MULTIPLIER"}
      else
        {data, "CRASH"}
      end

    data =
      Enum.reduce(data.bets, data, fn
        {key, %{status: :active} = b}, d ->
          after_fun = fn ->
            notify(b.session_id, "BET_LOST", %{
              bet_id: b.bet_id,
              panel: b.panel,
              crash_x10000: r.crash
            })
          end

          d |> put_in([Access.key(:bets), key, :status], :lost) |> add_after(after_fun)

        _, d ->
          d
      end)

    seed = hex(r.seed)
    salt = hex(data.chain.salt)

    data =
      data
      |> journal("ROUND_CRASHED", %{
        crash_x10000: r.crash,
        crash_at: r.crash_at,
        end_reason: end_reason,
        seed: seed,
        salt: salt
      })
      |> flush!()

    fenced!(
      data,
      "UPDATE rt.round SET state = 'CRASHED', crash_x10000 = $4, crash_at = $5, seed_hex = $6, updated_at = now() WHERE round_id = $3::text::uuid",
      [r.id, r.crash, r.crash_at, seed]
    )

    data = %{data | recent: Enum.take([r.crash | data.recent], 30)}

    data =
      broadcast(data, "ROUND_CRASHED", %{
        crash_x10000: r.crash,
        crash_at: r.crash_at,
        end_reason: end_reason,
        seed: seed,
        salt: salt,
        chain_id: data.chain.chain_id,
        chain_index: r.chain_index
      })

    publish_snapshot(data, "CRASHED")
  end

  # ---- betting -----------------------------------------------------------------------------

  defp handle_place_bet(cmd, state, data) do
    r = data.round
    key = {cmd.session_id, cmd.panel}

    cond do
      r == nil or cmd.round_id != r.id ->
        reject(data, cmd, "ROUND_MISMATCH")

      state != :betting_open or cmd.received_at >= r.close_at ->
        reject(data, cmd, "BETTING_CLOSED")

      cmd.panel < 0 or cmd.panel >= data.rules.panels ->
        reject(data, cmd, "INVALID_REQUEST")

      match?(%{command_id: c} when c == cmd.command_id, data.pending[key]) ->
        data

      match?(%{command_id: c} when c == cmd.command_id, data.bets[key]) ->
        b = data.bets[key]
        notify(cmd.session_id, "BET_ACCEPTED", accepted_payload(b))
        data

      Map.has_key?(data.pending, key) or Map.has_key?(data.bets, key) ->
        reject(data, cmd, "PANEL_BUSY")

      true ->
        timeout =
          min(
            data.timing |> Map.get(:bet_timeout_ms, platform_timeout()),
            r.launch_at - now() - 50
          )

        body = %{
          session_id: cmd.session_id,
          round_id: r.id,
          command_id: cmd.command_id,
          panel: cmd.panel,
          stake: cmd.stake,
          auto_cashout_x10000: cmd.auto,
          debit_deadline_ms: r.launch_at - 50,
          fencing_token: data.token,
          stream_id: data.stream
        }

        task =
          Task.Supervisor.async_nolink(LuxRt.TaskSupervisor, fn ->
            platform_client().place_bet(body, max(timeout, 1))
          end)

        pending = Map.put(cmd, :ref, task.ref)

        %{
          data
          | pending: Map.put(data.pending, key, pending),
            tasks: Map.put(data.tasks, task.ref, key)
        }
    end
  end

  defp handle_bet_result(ref, result, state, data) do
    {key, tasks} = Map.pop(data.tasks, ref)
    data = %{data | tasks: tasks}

    cond do
      key == nil ->
        data

      Map.has_key?(data.excluded, key) and data.excluded[key].ref == ref ->
        p = data.excluded[key]

        payload =
          case result["status"] do
            "REJECTED" ->
              %{command_id: p.command_id, panel: p.panel, code: result["code"], refund: "NONE"}

            _ ->
              %{command_id: p.command_id, panel: p.panel, code: "LATE", refund: "PENDING"}
          end

        notify(p.session_id, "BET_REJECTED", payload)
        data

      not Map.has_key?(data.pending, key) ->
        data

      true ->
        p = data.pending[key]

        case {result["status"], state} do
          {"ACCEPTED", s} when s in [:betting_open, :betting_closed] ->
            stake = String.to_integer(result["stake"] || p.stake)
            max_win = String.to_integer(result["max_win"])

            bet = %{
              key: key,
              bet_id: result["bet_id"],
              session_id: p.session_id,
              panel: p.panel,
              command_id: p.command_id,
              stake: stake,
              auto: p.auto,
              max_win: max_win,
              k_eff: effective_target(p.auto, stake, max_win, data.rules.max_multiplier_x10000),
              status: :active,
              cashout: nil,
              payout: nil
            }

            data = %{
              data
              | pending: Map.delete(data.pending, key),
                bets: Map.put(data.bets, key, bet)
            }

            data
            |> journal("BET_ADMITTED", %{
              bet_id: bet.bet_id,
              session_id: bet.session_id,
              panel: bet.panel
            })
            |> add_after(fn ->
              notify(bet.session_id, "BET_ACCEPTED", accepted_payload(bet, result["balance"]))
            end)
            |> schedule_flush()

          {"REJECTED", _} ->
            notify(p.session_id, "BET_REJECTED", %{
              command_id: p.command_id,
              panel: p.panel,
              code: result["code"],
              refund: "NONE"
            })

            %{data | pending: Map.delete(data.pending, key)}

          _ ->
            # UNKNOWN (or ACCEPTED too late): keep it pending so launch journals the exclusion,
            # which guarantees Django refunds the stake if the debit did land.
            notify(p.session_id, "BET_REJECTED", %{
              command_id: p.command_id,
              panel: p.panel,
              code: "UNCERTAIN",
              refund: "PENDING"
            })

            data
        end
    end
  end

  defp effective_target(auto, stake, max_win, max_mult) do
    k = Multiplier.effective_target(auto, stake, max_win, max_mult)

    trigger =
      cond do
        k == max_mult -> "MAX_MULTIPLIER"
        auto != nil and k == auto -> "AUTO"
        true -> "MAX_WIN"
      end

    {k, trigger}
  end

  defp accepted_payload(b, balance \\ nil) do
    base = %{
      command_id: b.command_id,
      bet_id: b.bet_id,
      panel: b.panel,
      stake: Integer.to_string(b.stake),
      auto_cashout_x10000: b.auto
    }

    if balance, do: Map.put(base, :balance, balance), else: base
  end

  # ---- cash-outs ---------------------------------------------------------------------------

  defp handle_cash_out(cmd, state, data) do
    r = data.round
    key = Enum.find_value(data.bets, fn {k, b} -> if b.bet_id == cmd.bet_id, do: k end)
    bet = key && data.bets[key]

    cond do
      bet == nil or bet.session_id != cmd.session_id ->
        cash_reject(data, cmd, "NOT_ACTIVE")

      bet.status == :cashed ->
        cash_reject(data, cmd, "ALREADY_CASHED_OUT")

      # Judged on the gateway receipt stamp against the crash instant, inside this single
      # process, so a cash-out and the crash can never both "win" (doc 06 §5.3).
      state != :flying or cmd.received_at >= r.crash_at or bet.status != :active ->
        cash_reject(data, cmd, "ROUND_ENDED")

      true ->
        elapsed = max(cmd.received_at - r.launch_at, 0)
        multiplier = Curve.at(data.table, elapsed)

        data
        |> accept_cashout(key, multiplier, "MANUAL", cmd.received_at, cmd.command_id)
        |> schedule_flush()
    end
  end

  defp cash_reject(data, cmd, code) do
    notify(cmd.session_id, "CASHOUT_REJECTED", %{
      command_id: cmd.command_id,
      bet_id: cmd.bet_id,
      code: code
    })

    data
  end

  defp accept_cashout(data, key, multiplier, trigger, received_at, command_id \\ nil) do
    bet = data.bets[key]
    payout = Multiplier.payout_minor(bet.stake, multiplier, bet.max_win)
    bet = %{bet | status: :cashed, cashout: multiplier, payout: payout}
    data = put_in(data.bets[key], bet)

    payload = %{
      bet_id: bet.bet_id,
      panel: bet.panel,
      cashout_x10000: multiplier,
      payout: Integer.to_string(payout),
      trigger: trigger
    }

    payload = if command_id, do: Map.put(payload, :command_id, command_id), else: payload

    data
    |> journal("CASHOUT_ACCEPTED", %{
      bet_id: bet.bet_id,
      cashout_x10000: multiplier,
      payout_minor: payout,
      trigger: trigger,
      received_at: received_at
    })
    |> add_after(fn -> notify(bet.session_id, "CASHOUT_ACCEPTED", payload) end)
  end

  defp build_auto_queue(data) do
    data.bets
    |> Enum.map(fn {key, b} -> {elem(b.k_eff, 0), elem(b.k_eff, 1), key} end)
    |> Enum.sort()
  end

  # Fires at the curve crossing time of the next target, never earlier (information-leak rule).
  defp auto_timer(%{auto_queue: [{k, _t, _key} | _]} = data) do
    if k <= data.round.crash do
      at = data.round.launch_at + Curve.crossing_time(data.table, k)
      [{{:timeout, :auto}, max(at - now(), 0), :auto}]
    else
      []
    end
  end

  defp auto_timer(_data), do: []

  defp run_auto_cashouts(data, elapsed) do
    current = Curve.at(data.table, elapsed)
    r = data.round

    {due, rest} =
      Enum.split_while(data.auto_queue, fn {k, _t, _key} -> k <= current and k <= r.crash end)

    data =
      Enum.reduce(due, data, fn {k, trigger, key}, d ->
        if d.bets[key].status == :active, do: accept_cashout(d, key, k, trigger, now()), else: d
      end)

    %{data | auto_queue: rest}
  end

  # ---- journal, broadcast, snapshots -------------------------------------------------------

  defp journal(data, type, payload) do
    seq = data.seq + 1

    entry = %{
      event_id: Ecto.UUID.generate(),
      stream_seq: seq,
      round_id: data.round.id,
      type: type,
      payload: payload
    }

    %{data | seq: seq, buf: [{:entry, entry} | data.buf]}
  end

  defp add_after(data, fun), do: %{data | buf: [{:after, fun} | data.buf]}

  defp schedule_flush(%{flush_scheduled: true} = data), do: data

  # Batches journal writes (e.g. cash-out bursts) into one fenced insert every few ms.
  defp schedule_flush(data) do
    Process.send_after(self(), :flush_now, data.timing.journal_flush_ms)
    %{data | flush_scheduled: true}
  end

  defp flush!(%{buf: []} = data), do: data

  defp flush!(data) do
    items = Enum.reverse(data.buf)
    entries = for {:entry, e} <- items, do: e

    case Journal.append(data.stream, data.holder, data.token, entries) do
      :ok ->
        for {:after, fun} <- items, do: fun.()
        Relay.poke()
        %{data | buf: [], flush_scheduled: false}

      {:error, :lease_lost} ->
        # Nothing in this batch was recorded, so nothing was acknowledged. Halt; recovery voids.
        exit(:lease_lost)
    end
  end

  defp broadcast(data, type, payload) do
    pub_seq = data.pub_seq + 1

    LuxRtWeb.Endpoint.broadcast("stream:" <> data.stream, type, %{
      type: type,
      v: 1,
      stream_id: data.stream,
      round_id: data.round && data.round.id,
      seq: pub_seq,
      server_ts: now(),
      data: payload
    })

    %{data | pub_seq: pub_seq}
  end

  defp notify(session_id, type, payload) do
    Phoenix.PubSub.broadcast(LuxRt.PubSub, "session:" <> session_id, {:lr_private, type, payload})
  end

  defp reject(data, cmd, code) do
    notify(cmd.session_id, "BET_REJECTED", %{
      command_id: cmd.command_id,
      panel: cmd.panel,
      code: code,
      refund: "NONE"
    })

    data
  end

  defp publish_snapshot(data, state) do
    r = data.round

    round =
      %{
        round_id: r.id,
        number: r.number,
        state: state,
        opens_at: r.opens_at,
        close_at: r.close_at,
        launch_at: r.launch_at,
        commitment: r.commitment,
        curve: curve_info(data)
      }
      |> then(fn m ->
        if state == "CRASHED",
          do: Map.merge(m, %{crash_x10000: r.crash, seed: hex(r.seed)}),
          else: m
      end)

    Snapshot.put(data.stream, %{
      stream_id: data.stream,
      seq: data.pub_seq,
      server_ts: now(),
      round: round,
      recent_crashes: data.recent
    })

    data
  end

  defp player_bets(data, session_id) do
    bets =
      for {_k, b} <- data.bets, b.session_id == session_id do
        %{
          panel: b.panel,
          bet_id: b.bet_id,
          command_id: b.command_id,
          status:
            case b.status do
              :active ->
                if data.round && now() >= data.round.launch_at, do: "ACTIVE", else: "ACCEPTED"

              :cashed ->
                "CASHED_OUT"

              :lost ->
                "LOST"
            end,
          stake: Integer.to_string(b.stake),
          auto_cashout_x10000: b.auto,
          cashout_x10000: b.cashout,
          payout: b.payout && Integer.to_string(b.payout)
        }
      end

    pending =
      for {{sid, panel}, p} <- data.pending, sid == session_id do
        %{
          panel: panel,
          command_id: p.command_id,
          status: "PENDING",
          stake: p.stake,
          auto_cashout_x10000: p.auto
        }
      end

    bets ++ pending
  end

  defp curve_info(data) do
    %{
      kind: "exp",
      # Fixed per deployment (the curve table and shared vectors depend on it), not per ruleset.
      lambda_per_ms: Application.fetch_env!(:lux_rt, :ruleset)[:curve_lambda_per_ms],
      table_hash: Curve.sha256(data.table)
    }
  end

  # ---- persistence helpers -----------------------------------------------------------------

  defp update_round(data, state) do
    fenced!(
      data,
      "UPDATE rt.round SET state = $4, updated_at = now() WHERE round_id = $3::text::uuid",
      [data.round.id, state]
    )
  end

  # Executes a statement only while holding the current lease (fenced write).
  defp fenced!(data, sql, params, opts \\ [])

  defp fenced!(data, sql, params, raw: true) do
    %{num_rows: n} = Repo.query!(sql, [data.stream, data.holder | params])
    if n != 1, do: exit(:lease_lost)
    :ok
  end

  defp fenced!(data, sql, params, _opts) do
    guarded =
      sql <>
        " AND EXISTS (SELECT 1 FROM rt.stream_lease l WHERE l.stream_id = $1 AND l.holder = $2 AND l.fencing_token = #{data.token})"

    %{num_rows: n} = Repo.query!(guarded, [data.stream, data.holder | params])
    if n != 1, do: exit(:lease_lost)
    :ok
  end

  defp safe_renew(data) do
    Lease.renew(data.stream, data.holder, data.token, data.timing.lease_ttl_ms)
  rescue
    _ -> :lost
  end

  defp renew_timer(data), do: {{:timeout, :renew}, data.timing.lease_renew_ms, :renew}

  defp platform_client, do: Application.get_env(:lux_rt, :platform_client, Platform)

  defp platform_timeout, do: Application.fetch_env!(:lux_rt, :platform)[:bet_timeout_ms]

  defp hex(bin), do: Base.encode16(bin, case: :lower)

  defp now, do: System.os_time(:millisecond)

  @doc false
  def unit, do: @unit
end
