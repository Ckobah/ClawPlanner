import { Body, Controller, Get, Post, Req, UseGuards } from '@nestjs/common';
import type { Request } from 'express';
import { AuthGuard } from './auth.guard';
import { AuthService } from './auth.service';
import { TelegramAuthDto } from './dto/telegram-auth.dto';

@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('telegram')
  async telegramLogin(@Body() dto: TelegramAuthDto) {
    return this.auth.telegramLogin(dto);
  }

  @UseGuards(AuthGuard)
  @Get('me')
  async me(@Req() req: Request) {
    const payload = req.user as { tg_id: number; is_admin: boolean };
    const user = await this.auth.getMe(payload.tg_id);
    return {
      user,
      is_admin: payload.is_admin,
    };
  }
}
