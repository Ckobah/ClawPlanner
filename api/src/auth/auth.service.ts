import { Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import crypto from 'crypto';
import { Repository } from 'typeorm';
import { User } from '../entities/user.entity';
import { TelegramAuthDto } from './dto/telegram-auth.dto';

type JwtPayload = {
  tg_id: number;
  is_admin: boolean;
};

@Injectable()
export class AuthService {
  constructor(
    private readonly jwtService: JwtService,
    private readonly config: ConfigService,
    @InjectRepository(User) private readonly users: Repository<User>,
  ) {}

  async telegramLogin(dto: TelegramAuthDto): Promise<{ token: string }> {
    const token = this.config.get<string>('TG_BOT_TOKEN');
    if (!token) {
      throw new UnauthorizedException('Bot token missing');
    }

    if (!this.verifyTelegramAuth(dto, token)) {
      throw new UnauthorizedException('Invalid Telegram signature');
    }

    const tgId = dto.id;
    const isAdmin = this.isAdmin(tgId);
    const tgIdString = String(tgId);

    let user = await this.users.findOne({ where: { tgId: tgIdString } });
    if (!user) {
      user = this.users.create({
        tgId: tgIdString,
        username: dto.username ?? null,
        firstName: dto.first_name ?? null,
        lastName: dto.last_name ?? null,
        isActive: true,
      });
    } else {
      user.username = dto.username ?? user.username ?? null;
      user.firstName = dto.first_name ?? user.firstName ?? null;
      user.lastName = dto.last_name ?? user.lastName ?? null;
      user.isActive = true;
    }

    await this.users.save(user);

    const payload: JwtPayload = { tg_id: tgId, is_admin: isAdmin };
    const jwt = await this.jwtService.signAsync(payload);
    return { token: jwt };
  }

  async getMe(tgId: number): Promise<User | null> {
    return this.users.findOne({ where: { tgId: String(tgId) } });
  }

  private isAdmin(tgId: number): boolean {
    const raw = this.config.get<string>('ADMIN_TG_IDS') ?? '';
    const admins = raw
      .split(',')
      .map((id) => id.trim())
      .filter(Boolean);
    return admins.includes(String(tgId));
  }

  private verifyTelegramAuth(dto: TelegramAuthDto, botToken: string): boolean {
    const data: Record<string, string> = {};
    Object.entries(dto).forEach(([key, value]) => {
      if (key === 'hash' || value === undefined || value === null) {
        return;
      }
      data[key] = String(value);
    });

    const dataCheckString = Object.keys(data)
      .sort()
      .map((key) => `${key}=${data[key]}`)
      .join('\n');

    const secretKey = crypto.createHash('sha256').update(botToken).digest();
    const hmac = crypto.createHmac('sha256', secretKey).update(dataCheckString).digest('hex');
    return hmac === dto.hash;
  }
}
