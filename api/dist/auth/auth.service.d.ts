import { JwtService } from '@nestjs/jwt';
import { ConfigService } from '@nestjs/config';
import { Repository } from 'typeorm';
import { User } from '../entities/user.entity';
import { TelegramAuthDto } from './dto/telegram-auth.dto';
export declare class AuthService {
    private readonly jwtService;
    private readonly config;
    private readonly users;
    constructor(jwtService: JwtService, config: ConfigService, users: Repository<User>);
    telegramLogin(dto: TelegramAuthDto): Promise<{
        token: string;
    }>;
    getMe(tgId: number): Promise<User | null>;
    private isAdmin;
    private verifyTelegramAuth;
}
