import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CanceledEvent } from '../entities/canceled-event.entity';
import { Event } from '../entities/event.entity';
import { User } from '../entities/user.entity';
import { AuthModule } from '../auth/auth.module';
import { EventsController } from './events.controller';
import { EventsService } from './events.service';

@Module({
  imports: [TypeOrmModule.forFeature([Event, User, CanceledEvent]), AuthModule],
  controllers: [EventsController],
  providers: [EventsService],
})
export class EventsModule {}
