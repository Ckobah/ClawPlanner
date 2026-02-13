declare namespace Express {
  export interface Request {
    user?: {
      tg_id: number;
      is_admin?: boolean;
    };
  }
}
