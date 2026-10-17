defmodule LuxRt.Rounds.Journal do
  @moduledoc """
  Append-only round facts (ADR-003). Inserts are fenced: a single statement that only writes if
  the caller still holds the stream's current lease token. Zero rows written means the lease is
  lost and the coordinator must halt.
  """

  alias LuxRt.Repo

  @type entry :: %{
          event_id: String.t(),
          stream_seq: integer(),
          round_id: String.t(),
          type: String.t(),
          payload: map()
        }

  @spec append(String.t(), String.t(), integer(), [entry()]) :: :ok | {:error, :lease_lost}
  def append(_stream_id, _holder, _token, []), do: :ok

  def append(stream_id, holder, token, entries) do
    now = DateTime.utc_now()

    {seqs, ids, rounds, types, payloads} =
      entries
      |> Enum.map(fn e ->
        {e.stream_seq, Ecto.UUID.dump!(e.event_id), Ecto.UUID.dump!(e.round_id), e.type,
         Jason.encode!(e.payload)}
      end)
      |> unzip5()

    %{num_rows: n} =
      Repo.query!(
        """
        INSERT INTO rt.round_journal
          (stream_id, stream_seq, event_id, round_id, type, payload, fencing_token, recorded_at)
        SELECT $1, s.seq, s.eid, s.rid, s.typ, s.pl::jsonb, $3, $4
          FROM unnest($5::bigint[], $6::uuid[], $7::uuid[], $8::text[], $9::text[])
               AS s(seq, eid, rid, typ, pl)
         WHERE EXISTS (SELECT 1 FROM rt.stream_lease l
                        WHERE l.stream_id = $1 AND l.holder = $2 AND l.fencing_token = $3)
        """,
        [stream_id, holder, token, now, seqs, ids, rounds, types, payloads]
      )

    if n == length(entries), do: :ok, else: {:error, :lease_lost}
  end

  defp unzip5(list) do
    Enum.reduce(Enum.reverse(list), {[], [], [], [], []}, fn {a, b, c, d, e},
                                                             {as, bs, cs, ds, es} ->
      {[a | as], [b | bs], [c | cs], [d | ds], [e | es]}
    end)
  end

  @doc "Highest stream_seq written so far (the coordinator continues from here)."
  def last_seq(stream_id) do
    %{rows: [[seq]]} =
      Repo.query!(
        "SELECT COALESCE(MAX(stream_seq), 0) FROM rt.round_journal WHERE stream_id = $1",
        [
          stream_id
        ]
      )

    seq
  end
end
