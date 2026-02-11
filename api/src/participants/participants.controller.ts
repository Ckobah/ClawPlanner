import { Body, Controller, Delete, Get, Req, UseGuards } from '@nestjs/common';
import type { Request } from 'express';
import { AuthGuard } from '../auth/auth.guard';
import { DeleteParticipantsDto } from './dto/delete-participants.dto';
import { ParticipantsService } from './participants.service';

@UseGuards(AuthGuard)
@Controller('participants')
export class ParticipantsController {
  constructor(private readonly participants: ParticipantsService) {}

  @Get()
  async list(@Req() req: Request) {
    const payload = req.user as { tg_id: number };
    return this.participants.listParticipants(payload.tg_id);
  }

  @Delete()
  async delete(@Req() req: Request, @Body() dto: DeleteParticipantsDto) {
    const payload = req.user as { tg_id: number };
    const removed = await this.participants.deleteParticipants(payload.tg_id, dto.tg_ids);
    return { removed };
  }
}
