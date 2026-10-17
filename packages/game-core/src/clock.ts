/**
 * Server clock estimate for rendering (doc 10 §7). Never used for deadlines: the server stamps
 * every command itself. Offset = median of samples of server_ts - (client midpoint).
 */
export class ServerClock {
  private samples: number[] = [];
  private offsetMs = 0;

  constructor(private readonly nowFn: () => number = () => Date.now()) {}

  /** Record a ping: client send time, client receive time, server receipt time. */
  sample(sentAt: number, receivedAt: number, serverTs: number): void {
    const midpoint = sentAt + (receivedAt - sentAt) / 2;
    this.samples.push(serverTs - midpoint);
    if (this.samples.length > 9) this.samples.shift();
    const sorted = [...this.samples].sort((a, b) => a - b);
    this.offsetMs = sorted[Math.floor(sorted.length / 2)] ?? 0;
  }

  /** Adopt a coarse offset from any server timestamp until pings arrive. */
  hint(serverTs: number): void {
    if (this.samples.length === 0) this.offsetMs = serverTs - this.nowFn();
  }

  get offset(): number {
    return this.offsetMs;
  }

  now(): number {
    return this.nowFn() + this.offsetMs;
  }
}
