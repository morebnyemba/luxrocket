export type Me = {
  email: string;
  role: string;
  mfa_enabled: boolean;
  must_change_password: boolean;
  step_up_valid: boolean;
  permissions: string[];
  operator: { id: string; name: string; status: string; real_money_enabled: boolean };
};

export type BetRow = {
  bet_id: string;
  round_id: string;
  panel: number;
  currency: string;
  stake: string;
  status: string;
  cashout_x10000: number | null;
  payout: string | null;
  created_at: string;
  player_id?: string;
};
