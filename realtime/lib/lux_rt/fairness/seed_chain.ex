defmodule LuxRt.Fairness.SeedChain do
  @moduledoc """
  Hash-chain seeds (doc 07 §6). `s_{i+1} = SHA256(s_i)`; terminal `s_N` is the public commitment.
  Round k uses `s_{N-k}`; its commitment is `s_{N-k+1}` (the previous round's revealed seed).

  Secrets (root seed and checkpoints) are AES-256-GCM encrypted with a KEK held outside the
  database and are only ever decrypted in coordinator memory.

  Lifecycle (doc 07 §6.1):

    * `commit/2` — the ceremony. Generates the chain and fixes a drand round at least
      `min_delay_s` in the future. Status `COMMITTED`: the terminal hash is public, the salt is
      not yet knowable by anyone, so the chain cannot have been picked for its outcomes.
    * `activate/1` — after the drand round is published and a four-eyes approval on the
      platform: `salt = drand.randomness(R)`, status `ACTIVE`, the previous chain is `RETIRED`.
    * `EXHAUSTED` — every index used; the coordinator halts until another chain is activated.

  Development and test builds may auto-create an `ACTIVE` chain with a locally random salt
  (`salt_source: "local-random"`); production (`auto_chain: false`) only ever plays activated
  chains.
  """

  import Ecto.Query
  require Logger
  alias LuxRt.Repo

  defstruct [:chain_id, :length, :salt, :salt_source, :checkpoint_every, :checkpoints, :terminal]

  @type t :: %__MODULE__{}

  # ---- loading -------------------------------------------------------------------------------

  @doc "The stream's ACTIVE chain, or nil."
  @spec active(String.t()) :: t() | nil
  def active(stream_id) do
    stream_id |> chain_query() |> where([c], c.status == "ACTIVE") |> Repo.one() |> hydrate()
  end

  @doc "Any chain by id (recovery needs the chain an interrupted round was created on)."
  @spec load(String.t()) :: t() | nil
  def load(chain_id) do
    from(c in "seed_chain", prefix: "rt", where: c.chain_id == type(^chain_id, Ecto.UUID))
    |> select_chain()
    |> Repo.one()
    |> hydrate()
  end

  @doc "Id of the stream's ACTIVE chain (cheap; checked at every round boundary)."
  @spec active_id(String.t()) :: String.t() | nil
  def active_id(stream_id) do
    Repo.one(
      from c in "seed_chain",
        prefix: "rt",
        where: c.stream_id == ^stream_id and c.status == "ACTIVE",
        select: type(c.chain_id, Ecto.UUID)
    )
  end

  @doc "The ACTIVE chain; in builds with `auto_chain: true`, creates a local one if none."
  @spec ensure_active(String.t()) :: t() | nil
  def ensure_active(stream_id) do
    case active(stream_id) do
      nil ->
        if config()[:auto_chain] do
          Logger.warning("#{stream_id}: no ACTIVE seed chain; creating a local-random dev chain")
          create_local(stream_id)
          active(stream_id)
        end

      chain ->
        chain
    end
  end

  defp chain_query(stream_id) do
    from(c in "seed_chain", prefix: "rt", where: c.stream_id == ^stream_id) |> select_chain()
  end

  defp select_chain(query) do
    select(query, [c], %{
      chain_id: c.chain_id,
      length: c.length,
      salt: c.salt,
      salt_source: c.salt_source,
      checkpoint_every: c.checkpoint_every,
      terminal_hash: c.terminal_hash
    })
  end

  defp hydrate(nil), do: nil

  defp hydrate(row) do
    rows =
      Repo.all(
        from cp in "seed_checkpoint",
          prefix: "rt",
          where: cp.chain_id == ^row.chain_id,
          select: {cp.idx, cp.seed_ct}
      )

    checkpoints = Map.new(rows, fn {idx, ct} -> {idx, decrypt(ct)} end)

    %__MODULE__{
      chain_id: Ecto.UUID.cast!(row.chain_id),
      length: row.length,
      salt: Base.decode16!(row.salt, case: :lower),
      salt_source: row.salt_source,
      checkpoint_every: row.checkpoint_every,
      checkpoints: checkpoints,
      terminal: Base.decode16!(row.terminal_hash, case: :lower)
    }
  end

  # ---- ceremony ------------------------------------------------------------------------------

  @doc """
  The commitment ceremony. Returns the public facts to publish: chain id, length, terminal hash
  and the drand round whose randomness will become the salt.

  Options: `:delay_s` (default and minimum: the configured `min_delay_s`), `:now` (unix seconds).
  """
  @spec commit(String.t(), keyword()) :: {:ok, map()} | {:error, String.t()}
  def commit(stream_id, opts \\ []) do
    drand = drand()
    min_delay = drand[:min_delay_s]
    delay = Keyword.get(opts, :delay_s, min_delay)
    now = Keyword.get(opts, :now, System.os_time(:second))

    cond do
      not (is_binary(stream_id) and stream_id =~ ~r/^[a-z0-9][a-z0-9-]{0,62}$/) ->
        {:error, "invalid stream id"}

      delay < min_delay ->
        {:error, "the drand round must be at least #{min_delay}s in the future"}

      true ->
        round = drand_round_at(now + delay)

        chain_id =
          insert_chain(stream_id, "COMMITTED", "", "drand-pending", %{
            drand_chain_hash: drand[:chain_hash],
            drand_round: round,
            committed_at: DateTime.from_unix!(now)
          })

        %{terminal_hash: terminal, length: n} = summary(chain_id)

        {:ok,
         %{
           chain_id: chain_id,
           stream: stream_id,
           length: n,
           terminal_hash: terminal,
           drand_chain_hash: drand[:chain_hash],
           drand_round: round,
           drand_round_time: drand_round_time(round)
         }}
    end
  end

  @doc """
  Activates a COMMITTED chain with the beacon of its committed drand round (platform event
  `seed_chain.activate`, emitted only after a four-eyes approval). Idempotent.

  The beacon must be internally consistent (`randomness == SHA256(signature)`, the drand
  definition). The BLS signature itself is published with the chain so any auditor can check
  it against the drand network's public key.
  """
  @spec activate(map()) :: :ok | {:error, atom()}
  def activate(%{
        "chain_id" => chain_id,
        "stream" => stream,
        "drand_round" => round,
        "randomness" => randomness,
        "signature" => signature
      })
      when is_binary(chain_id) and is_binary(stream) and is_integer(round) and
             is_binary(randomness) and is_binary(signature) do
    with {:ok, uuid} <- Ecto.UUID.cast(chain_id),
         {:ok, sig} <- Base.decode16(signature, case: :mixed),
         {:ok, rnd} <- Base.decode16(randomness, case: :mixed),
         true <- byte_size(rnd) == 32 and :crypto.hash(:sha256, sig) == rnd do
      do_activate(
        uuid,
        stream,
        round,
        Base.encode16(rnd, case: :lower),
        String.downcase(signature)
      )
    else
      false -> {:error, :bad_beacon}
      _ -> {:error, :malformed}
    end
  end

  def activate(_), do: {:error, :malformed}

  defp do_activate(chain_id, stream, round, salt, signature) do
    Repo.transaction(fn ->
      %{rows: rows} =
        Repo.query!(
          """
          SELECT status, stream_id, drand_round, drand_chain_hash, salt FROM rt.seed_chain
           WHERE chain_id = $1::text::uuid FOR UPDATE
          """,
          [chain_id]
        )

      case rows do
        [] ->
          Repo.rollback(:not_found)

        [[_, s, _, _, _]] when s != stream ->
          Repo.rollback(:wrong_stream)

        [["ACTIVE", _, ^round, _, ^salt]] ->
          :already_active

        [["COMMITTED", _, ^round, hash, _]] ->
          Repo.query!(
            """
            UPDATE rt.seed_chain SET status = 'RETIRED', retired_at = now()
             WHERE stream_id = $1 AND status = 'ACTIVE'
            """,
            [stream]
          )

          Repo.query!(
            """
            UPDATE rt.seed_chain
               SET status = 'ACTIVE', salt = $2, salt_source = $3, drand_signature = $4,
                   activated_at = now()
             WHERE chain_id = $1::text::uuid
            """,
            [chain_id, salt, "drand:#{hash}:#{round}", signature]
          )

          :activated

        [["COMMITTED", _, _, _, _]] ->
          Repo.rollback(:wrong_round)

        [[_, _, _, _, _]] ->
          Repo.rollback(:invalid_state)
      end
    end)
    |> case do
      {:ok, outcome} ->
        Logger.info("#{stream}: seed chain #{chain_id} #{outcome}")
        :ok

      {:error, why} ->
        Logger.error("#{stream}: refusing to activate seed chain #{chain_id}: #{why}")
        {:error, why}
    end
  end

  @doc "Marks a fully used chain EXHAUSTED (the coordinator then waits for a new activation)."
  def exhaust(chain_id) do
    Repo.query!(
      """
      UPDATE rt.seed_chain SET status = 'EXHAUSTED', retired_at = now()
       WHERE chain_id = $1::text::uuid AND status = 'ACTIVE'
      """,
      [chain_id]
    )

    :ok
  end

  # drand round r is published at genesis + (r - 1) * period.
  def drand_round_at(unix_s) do
    d = drand()
    max(div(unix_s - d[:genesis_time] + d[:period_s] - 1, d[:period_s]) + 1, 1)
  end

  def drand_round_time(round), do: drand()[:genesis_time] + (round - 1) * drand()[:period_s]

  defp create_local(stream_id) do
    salt = :crypto.strong_rand_bytes(32) |> Base.encode16(case: :lower)
    now = DateTime.utc_now()

    insert_chain(stream_id, "ACTIVE", salt, "local-random", %{
      committed_at: now,
      activated_at: now
    })
  end

  defp insert_chain(stream_id, status, salt, salt_source, extra) do
    cfg = config()
    n = cfg[:chain_length]
    every = cfg[:checkpoint_every]
    root = :crypto.strong_rand_bytes(32)
    chain_id = Ecto.UUID.generate()

    {terminal, checkpoints} =
      Enum.reduce(0..(n - 1)//1, {root, [{0, root}]}, fn i, {seed, cps} ->
        next = :crypto.hash(:sha256, seed)
        cps = if rem(i + 1, every) == 0, do: [{i + 1, next} | cps], else: cps
        {next, cps}
      end)

    row =
      Map.merge(
        %{
          chain_id: Ecto.UUID.dump!(chain_id),
          stream_id: stream_id,
          length: n,
          terminal_hash: Base.encode16(terminal, case: :lower),
          salt: salt,
          salt_source: salt_source,
          root_seed_ct: encrypt(root),
          checkpoint_every: every,
          status: status,
          inserted_at: DateTime.utc_now()
        },
        extra
      )

    {:ok, _} =
      Repo.transaction(fn ->
        Repo.insert_all("seed_chain", [row], prefix: "rt")

        checkpoints
        |> Enum.map(fn {idx, seed} ->
          %{chain_id: Ecto.UUID.dump!(chain_id), idx: idx, seed_ct: encrypt(seed)}
        end)
        |> Enum.chunk_every(1_000)
        |> Enum.each(&Repo.insert_all("seed_checkpoint", &1, prefix: "rt"))
      end)

    chain_id
  end

  defp summary(chain_id) do
    Repo.one(
      from c in "seed_chain",
        prefix: "rt",
        where: c.chain_id == type(^chain_id, Ecto.UUID),
        select: %{terminal_hash: c.terminal_hash, length: c.length}
    )
  end

  # ---- seeds ---------------------------------------------------------------------------------

  @doc "Seed at chain index i (s_i)."
  @spec seed_at(t(), non_neg_integer()) :: binary()
  def seed_at(%__MODULE__{length: n} = chain, i) when i >= 0 and i <= n do
    base = div(i, chain.checkpoint_every) * chain.checkpoint_every
    start = Map.fetch!(chain.checkpoints, base)
    Enum.reduce(1..(i - base)//1, start, fn _, s -> :crypto.hash(:sha256, s) end)
  end

  @doc "Seed for round k (1-based): s_{N-k}."
  def round_seed(%__MODULE__{length: n} = chain, k) when k >= 1 and k <= n,
    do: seed_at(chain, n - k)

  @doc "Commitment shown before round k: s_{N-k+1} (the terminal hash for k = 1)."
  def round_commitment(%__MODULE__{length: n} = chain, k), do: seed_at(chain, n - k + 1)

  defp config, do: Application.fetch_env!(:lux_rt, :fairness)
  defp drand, do: Application.fetch_env!(:lux_rt, :drand)

  # ---- envelope encryption -----------------------------------------------------------------

  defp kek do
    case config()[:seed_kek_b64] do
      nil ->
        if Application.get_env(:lux_rt, :dev_derived_kek, false),
          do: :crypto.hash(:sha256, "luxrocket development-only seed KEK"),
          else: raise("SEED_KEK_B64 is not configured")

      b64 ->
        key = Base.decode64!(b64)
        if byte_size(key) != 32, do: raise("seed KEK must be 32 bytes")
        key
    end
  end

  defp encrypt(plain) do
    iv = :crypto.strong_rand_bytes(12)
    {ct, tag} = :crypto.crypto_one_time_aead(:aes_256_gcm, kek(), iv, plain, "lux-seed", true)
    iv <> tag <> ct
  end

  defp decrypt(<<iv::binary-12, tag::binary-16, ct::binary>>) do
    case :crypto.crypto_one_time_aead(:aes_256_gcm, kek(), iv, ct, "lux-seed", tag, false) do
      :error -> raise "seed decryption failed (wrong KEK?)"
      plain -> plain
    end
  end
end
