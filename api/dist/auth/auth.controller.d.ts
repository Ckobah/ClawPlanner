import type { Request } from 'express';
import { AuthService } from './auth.service';
import { TelegramAuthDto } from './dto/telegram-auth.dto';
export declare class AuthController {
    private readonly auth;
    constructor(auth: AuthService);
    telegramLogin(dto: TelegramAuthDto): Promise<{
        token: string;
    }>;
    me(req: Request): Promise<{
        user: import("../entities/user.entity").User | null;
        is_admin: boolean;
    }>;
}
