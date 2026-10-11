defmodule LuxRt.Rounds.Lease do
  @moduledoc """
  Coordinator ownership via a Postgres lease with a fencing token (ADR-004, doc 06 §3).

  Acquiring increments the fencing token. Every journal write is conditional on holding the
  current token, so a coordinator that has lost its lease cannot record anything.
  """

  alias LuxRt.Repo

  @doc "Try to acquire or renew. Returns {:ok, fencing_token} or :taken."
  @spec acquire(String.t(), String.t(), pos_integer()) :: {:ok, integer()} | :taken
  def acquire(stream_id, holder, ttl_ms) do
    Repo.query!(
      """
      INSERT INTO rt.stream_lease (stream_id, holder, fencing_token, expires_at)
      VALUES ($1, '', 0, now() - interval '1 second')
      ON CONFLICT (stream_id) DO NOTHING
      """,
      [stream_id]
    )

    %{rows: rows} =
      Repo.query!(
        """
        UPDATE rt.stream_lease
           SET fencing_token = CASE WHEN holder = $2 AND expires_at > now()
                                    THEN fencing_token ELSE fencing_token + 1 END,
               holder = $2,
               expires_at = now() + ($3::bigint * interval '1 millisecond')
         WHERE stream_id = $1 AND (expires_at < now() OR holder = $2)
         RETURNING fencing_token
        """,
        [stream_id, holder, ttl_ms]
      )

    case rows do
      [[token]] -> {:ok, token}
      [] -> :taken
    end
  end

  @doc "Renew only if we still hold exactly this token."
  @spec renew(String.t(), String.t(), integer(), pos_integer()) :: :ok | :lost
  def renew(stream_id, holder, token, ttl_ms) do
    %{num_rows: n} =
      Repo.query!(
        """
        UPDATE rt.stream_lease SET expires_at = now() + ($4::bigint * interval '1 millisecond')
         WHERE stream_id = $1 AND holder = $2 AND fencing_token = $3
        """,
        [stream_id, holder, token, ttl_ms]
      )

    if n == 1, do: :ok, else: :lost
  end

  @doc "Release at a round boundary (planned handover, no void)."
  def release(stream_id, holder, token) do
    Repo.query!(
      "UPDATE rt.stream_lease SET expires_at = now() WHERE stream_id = $1 AND holder = $2 AND fencing_token = $3",
      [stream_id, holder, token]
    )

    :ok
  end
end
