defmodule LuxRt.Fairness.SeedChain do
  @moduledoc """
  Hash-chain seeds (doc 07 §6). `s_{i+1} = SHA256(s_i)`; terminal `s_N` is the public commitment.
  Round k uses `s_{N-k}`; its commitment is `s_{N-k+1}` (the previous round's revealed seed).

  Secrets (root seed and checkpoints) are AES-256-GCM encrypted with a KEK held outside the
  database and are only ever decrypted in coordinator memory.

  Note: in this build the salt is a random value fixed at chain creation (`salt_source:
  "local-random"`). Production fixes it from a public randomness beacon round announced at
  commitment time (drand), which proves the chain was not chosen after the fact.
  """

  import Ecto.Query
  alias LuxRt.Repo

  defstruct [:chain_id, :length, :salt, :checkpoint_every, :checkpoints, :terminal]

  @type t :: %__MODULE__{}

  @doc "Loads the active chain for a stream, creating one if none exists."
  @spec load_or_create(String.t()) :: t()
  def load_or_create(stream_id) do
    case active_row(stream_id) do
      nil -> create(stream_id) && load_or_create(stream_id)
      row -> hydrate(row)
    end
  end

  defp active_row(stream_id) do
    Repo.one(
      from c in "seed_chain",
        prefix: "rt",
        where: c.stream_id == ^stream_id and c.status == "ACTIVE",
        order_by: [desc: c.inserted_at],
        limit: 1,
        select: %{
          chain_id: c.chain_id,
          length: c.length,
          salt: c.salt,
          checkpoint_every: c.checkpoint_every,
          terminal_hash: c.terminal_hash
        }
    )
  end

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
      checkpoint_every: row.checkpoint_every,
      checkpoints: checkpoints,
      terminal: Base.decode16!(row.terminal_hash, case: :lower)
    }
  end

  @doc "Generates and stores a new chain (development ceremony)."
  def create(stream_id) do
    cfg = Application.fetch_env!(:lux_rt, :fairness)
    n = cfg[:chain_length]
    every = cfg[:checkpoint_every]
    root = :crypto.strong_rand_bytes(32)
    salt = :crypto.strong_rand_bytes(32)
    chain_id = Ecto.UUID.generate()

    {terminal, checkpoints} =
      Enum.reduce(0..(n - 1)//1, {root, [{0, root}]}, fn i, {seed, cps} ->
        next = :crypto.hash(:sha256, seed)
        cps = if rem(i + 1, every) == 0, do: [{i + 1, next} | cps], else: cps
        {next, cps}
      end)

    Repo.transaction(fn ->
      Repo.insert_all(
        "seed_chain",
        [
          %{
            chain_id: Ecto.UUID.dump!(chain_id),
            stream_id: stream_id,
            length: n,
            terminal_hash: Base.encode16(terminal, case: :lower),
            salt: Base.encode16(salt, case: :lower),
            salt_source: "local-random",
            root_seed_ct: encrypt(root),
            checkpoint_every: every,
            status: "ACTIVE",
            inserted_at: DateTime.utc_now()
          }
        ],
        prefix: "rt"
      )

      checkpoints
      |> Enum.map(fn {idx, seed} ->
        %{chain_id: Ecto.UUID.dump!(chain_id), idx: idx, seed_ct: encrypt(seed)}
      end)
      |> Enum.chunk_every(1_000)
      |> Enum.each(&Repo.insert_all("seed_checkpoint", &1, prefix: "rt"))
    end)

    chain_id
  end

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

  # ---- envelope encryption -----------------------------------------------------------------

  defp kek do
    case Application.fetch_env!(:lux_rt, :fairness)[:seed_kek_b64] do
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
