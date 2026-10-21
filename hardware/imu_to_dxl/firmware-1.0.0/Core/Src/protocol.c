#include "protocol.h"
#include <string.h>

/* Feetech FT-SCS one-wire slave, independent implementation of the documented
 * FF FF ID LEN INST PARAMS CK framing (single-byte additive checksum).
 * No vendor protocol source is incorporated. */

#define BROADCAST_ID 254u
#define INST_PING    0x01u
#define INST_READ    0x02u
#define INST_WRITE   0x03u
#define INST_SYNC_READ  0x82u
#define INST_SYNC_WRITE 0x83u

uint8_t proto_checksum(const uint8_t *bytes, uint16_t length)
{
    uint16_t sum = 0u;
    uint16_t i;
    for (i = 0u; i < length; ++i) {
        sum = (uint16_t)(sum + bytes[i]);
    }
    return (uint8_t)(~(uint8_t)(sum & 0xFFu));
}

static void cancel_reply(proto_context *ctx)
{
    if (ctx->pending != 0u) {
        ++ctx->cancelled_replies;
    }
    ctx->pending = 0u;
    ctx->tx_length = 0u;
}

void proto_reset_receiver(proto_context *ctx)
{
    ctx->rx_length = 0u;
    ctx->rx_expected = 0u;
    cancel_reply(ctx);
}

void proto_init(proto_context *ctx, proto_read_fn read_registers,
                proto_write_fn write_registers, proto_send_fn send, void *user)
{
    memset(ctx, 0, sizeof(*ctx));
    ctx->read = read_registers;
    ctx->write = write_registers;
    ctx->send = send;
    ctx->user = user;
}

static int owned(uint16_t address)
{
    return address <= 9u;
}

static uint8_t owned_value(uint16_t address)
{
    switch (address) {
    case 0u: return PROTO_FIRMWARE_MAJOR;
    case 1u: return PROTO_FIRMWARE_MINOR;
    case 2u: return PROTO_ENDIAN;
    case 3u: return (uint8_t)(PROTO_MODEL_NUMBER & 0xFFu);
    case 4u: return (uint8_t)(PROTO_MODEL_NUMBER >> 8);
    case 5u: return PROTO_DEVICE_ID;
    case 6u: return PROTO_BAUD_CODE;
    case 8u: return PROTO_STATUS_LEVEL;
    default: return 0u; /* 7, 9 reserved. */
    }
}

static uint8_t read_table(proto_context *ctx, uint8_t address,
                          uint8_t length, uint8_t *out)
{
    uint8_t offset = 0u;
    while (offset < length) {
        uint8_t here = (uint8_t)(address + offset);
        if (owned(here)) {
            out[offset++] = owned_value(here);
        } else {
            uint8_t run = 1u;
            uint8_t error;
            while ((uint16_t)offset + run < length &&
                   !owned((uint8_t)(address + offset + run))) {
                ++run;
            }
            if (ctx->read == 0) {
                return PROTO_ERR_ACCESS;
            }
            error = ctx->read(ctx->user, here, run, out + offset);
            if (error != PROTO_OK) {
                return error;
            }
            offset = (uint8_t)(offset + run);
        }
    }
    return PROTO_OK;
}

static uint8_t write_table(proto_context *ctx, uint8_t address,
                           uint8_t length, const uint8_t *data)
{
    uint8_t i;
    if (length == 0u) {
        return PROTO_ERR_LENGTH;
    }
    /* Identity/configuration area is read-only; ID and baud are fixed. */
    for (i = 0u; i < length; ++i) {
        if (owned((uint16_t)(address + i))) {
            return PROTO_ERR_ACCESS;
        }
    }
    return ctx->write != 0
        ? ctx->write(ctx->user, address, length, data) : PROTO_ERR_ACCESS;
}

/* Caller places data payload at tx[5]. Frame: FF FF ID LEN ERR data CK. */
static void make_status(proto_context *ctx, uint8_t error, uint16_t data_length)
{
    uint16_t end = (uint16_t)(5u + data_length);
    ctx->tx[0] = 0xFFu;
    ctx->tx[1] = 0xFFu;
    ctx->tx[2] = PROTO_DEVICE_ID;
    ctx->tx[3] = (uint8_t)(2u + data_length);
    ctx->tx[4] = error;
    ctx->tx[end] = proto_checksum(ctx->tx + 2u, (uint16_t)(end - 2u));
    ctx->tx_length = (uint16_t)(end + 1u);
}

static void schedule_reply(proto_context *ctx, uint32_t now_us, int preceding)
{
    ctx->transaction_start_us = now_us;
    ctx->reply_due_us = now_us;
    ctx->pending = preceding < 0 ? 1u : 2u;
    ctx->preceding_id = (uint8_t)preceding;
}

static void reply_error(proto_context *ctx, uint8_t error, uint32_t now_us)
{
    make_status(ctx, error, 0u);
    schedule_reply(ctx, now_us, -1);
}

static void reply_read(proto_context *ctx, uint8_t address, uint8_t length,
                       uint32_t now_us, int preceding)
{
    uint8_t error = read_table(ctx, address, length, ctx->tx + 5u);
    make_status(ctx, error, error == PROTO_OK ? length : 0u);
    schedule_reply(ctx, now_us, preceding);
}

/* All participating IDs must be unique, real device IDs (< 253). No device is
 * allowed to start a response for a malformed list, even when its own entry is
 * valid. */
static int valid_id_list(const uint8_t *parameters, uint16_t length,
                         uint16_t start)
{
    uint16_t i;
    uint16_t j;
    if (length <= start) {
        return 0;
    }
    for (i = start; i < length; ++i) {
        if (parameters[i] > 252u) {
            return 0;
        }
        for (j = start; j < i; ++j) {
            if (parameters[i] == parameters[j]) {
                return 0;
            }
        }
    }
    return 1;
}

static int valid_read_range(uint8_t address, uint8_t length)
{
    return length != 0u && length <= PROTO_MAX_READ &&
           (uint16_t)address + length <= 256u;
}

static void execute(proto_context *ctx, uint32_t now_us)
{
    uint8_t id = ctx->rx[2];
    uint8_t instruction = ctx->rx[4];
    uint8_t *p = ctx->rx + 5u;
    uint8_t n = (uint8_t)(ctx->rx[3] - 2u); /* parameter count */
    uint8_t i;

    /* Waiting for the preceding sync-read device: Feetech has no status marker,
     * so ANY checksum-valid frame from that ID means its turn was consumed.
     * A fresh controller frame (to us or broadcast) aborts the transaction. */
    if (ctx->pending == 2u) {
        if (id == ctx->preceding_id &&
            (uint32_t)(now_us - ctx->transaction_start_us) <
                PROTO_TRANSACTION_TIMEOUT_US) {
            ctx->pending = 1u;
            ctx->reply_due_us = now_us;
        }
        if (id != PROTO_DEVICE_ID && id != BROADCAST_ID) {
            return;
        }
        cancel_reply(ctx);
    }

    if (id != PROTO_DEVICE_ID && id != BROADCAST_ID) {
        return;
    }
    switch (instruction) {
    case INST_PING: /* Addressed only, empty status. Broadcast ping is silent. */
        if (id == BROADCAST_ID || n != 0u) {
            if (n != 0u) { ++ctx->malformed_packets; }
            return;
        }
        make_status(ctx, PROTO_OK, 0u);
        schedule_reply(ctx, now_us, -1);
        break;
    case INST_READ: /* Never executed on broadcast ID. */
        if (id == BROADCAST_ID) {
            return;
        }
        if (n != 2u) {
            reply_error(ctx, PROTO_ERR_LENGTH, now_us);
        } else if (!valid_read_range(p[0], p[1])) {
            reply_error(ctx, p[1] == 0u ? PROTO_ERR_LENGTH : PROTO_ERR_RANGE,
                        now_us);
        } else {
            reply_read(ctx, p[0], p[1], now_us, -1);
        }
        break;
    case INST_WRITE:
        if (n < 1u) {
            if (id == PROTO_DEVICE_ID) {
                reply_error(ctx, PROTO_ERR_LENGTH, now_us);
            }
            return;
        }
        {
            uint8_t error = write_table(ctx, p[0], (uint8_t)(n - 1u), p + 1u);
            if (id == PROTO_DEVICE_ID) {
                reply_error(ctx, error, now_us);
            }
        }
        break;
    case INST_SYNC_READ: {
        uint8_t address;
        uint8_t length;
        /* Sequential bus-sniff turns. Measured on Feetech servos (firmware
         * 3.46, 1 Mbit): when a non-servo device is FIRST in the list, the
         * next servo starts one byte time before our checksum bit cell and
         * corrupts it; IMU in middle/last positions is 100% reliable. Hosts
         * must place ID 200 after the servos in the sync-read ID list. */
        if (id != BROADCAST_ID || n < 3u || !valid_id_list(p, n, 2u)) {
            if (id == BROADCAST_ID) { ++ctx->malformed_packets; }
            return;
        }
        address = p[0];
        length = p[1];
        if (!valid_read_range(address, length)) {
            ++ctx->malformed_packets;
            return;
        }
        for (i = 2u; i < n; ++i) {
            if (p[i] == PROTO_DEVICE_ID) {
                reply_read(ctx, address, length, now_us,
                           i == 2u ? -1 : (int)p[i - 1u]);
                return;
            }
        }
        break;
    }
    case INST_SYNC_WRITE: {
        uint8_t address;
        uint8_t dlen;
        if (id != BROADCAST_ID || n < 2u) {
            return;
        }
        address = p[0];
        dlen = p[1];
        /* Header + whole segments, stride dlen+1, IDs valid and unique. */
        if (dlen == 0u || (uint16_t)(n - 2u) % (uint16_t)(dlen + 1u) != 0u) {
            ++ctx->malformed_packets;
            return;
        }
        {
            uint16_t k;
            for (k = 2u; k < n; k = (uint16_t)(k + dlen + 1u)) {
                uint16_t j2;
                if (p[k] > 252u) { ++ctx->malformed_packets; return; }
                for (j2 = 2u; j2 < k; j2 = (uint16_t)(j2 + dlen + 1u)) {
                    if (p[k] == p[j2]) { ++ctx->malformed_packets; return; }
                }
            }
            for (k = 2u; k < n; k = (uint16_t)(k + dlen + 1u)) {
                if (p[k] == PROTO_DEVICE_ID) {
                    (void)write_table(ctx, address, dlen, p + k + 1u);
                    return;
                }
            }
        }
        break;
    }
    default:
        /* Unknown instructions stay silent. */
        break;
    }
}

static int complete_packet(proto_context *ctx, uint32_t now_us)
{
    uint16_t end = (uint16_t)(ctx->rx_expected - 1u);
    if (proto_checksum(ctx->rx + 2u, (uint16_t)(end - 2u)) != ctx->rx[end]) {
        ++ctx->checksum_errors;
        return 0;
    }
    ++ctx->rx_packets;
    execute(ctx, now_us);
    return 1;
}

void proto_feed(proto_context *ctx, uint8_t byte, uint32_t now_us)
{
    if (ctx->rx_length != 0u &&
        (uint32_t)(now_us - ctx->last_byte_us) > PROTO_BYTE_TIMEOUT_US) {
        ctx->rx_length = 0u;
        ctx->rx_expected = 0u;
        ++ctx->receive_timeouts;
    }
    /* A pending response loses its turn as soon as anyone else uses the bus.
     * The application MUST drain RX before calling proto_poll. */
    if (ctx->pending == 1u) {
        cancel_reply(ctx);
    }
    ctx->last_byte_us = now_us;

    if (ctx->rx_length < 2u) {
        if (byte == 0xFFu) {
            ctx->rx[ctx->rx_length++] = 0xFFu;
        } else {
            ctx->rx_length = 0u;
        }
        return;
    }
    if (ctx->rx_length == 2u) {
        if (byte == 0xFFu) {
            /* Extra leading FFs are tolerated as header-search noise. */
            return;
        }
        if (byte == 0u || byte == 255u) {
            /* Invalid ID (0 or 0xFF); restart header search. */
            ctx->rx_length = 0u;
            ++ctx->malformed_packets;
            return;
        }
        ctx->rx[2] = byte;
        ctx->rx_length = 3u;
        return;
    }
    if (ctx->rx_length == 3u) {
        uint8_t wire_length = byte;
        if (wire_length < 2u || wire_length > PROTO_MAX_FRAME_LEN) {
            ctx->rx_length = 0u;
            ctx->rx_expected = 0u;
            ++ctx->malformed_packets;
            return;
        }
        ctx->rx[3] = wire_length;
        ctx->rx_expected = (uint16_t)(4u + wire_length);
        ctx->rx_length = 4u;
        return;
    }
    ctx->rx[ctx->rx_length++] = byte;
    if (ctx->rx_expected != 0u && ctx->rx_length == ctx->rx_expected) {
        uint16_t suffix = 2u;
        if (complete_packet(ctx, now_us)) {
            suffix = 0u;
        }
        /* A falsely short length can end halfway into the next header. */
        while (suffix != 0u && ctx->rx[ctx->rx_expected - suffix] != 0xFFu) {
            --suffix;
        }
        if (suffix != 0u) {
            ctx->rx[0] = 0xFFu;
            ctx->rx[1] = 0xFFu;
        }
        ctx->rx_length = suffix;
        ctx->rx_expected = 0u;
    }
}

void proto_poll(proto_context *ctx, uint32_t now_us)
{
    if (ctx->rx_length != 0u &&
        (uint32_t)(now_us - ctx->last_byte_us) > PROTO_BYTE_TIMEOUT_US) {
        ctx->rx_length = 0u;
        ctx->rx_expected = 0u;
        ++ctx->receive_timeouts;
    }
    if (ctx->pending == 2u &&
        (uint32_t)(now_us - ctx->transaction_start_us) >=
            PROTO_TRANSACTION_TIMEOUT_US) {
        cancel_reply(ctx);
    }
    if (ctx->pending == 1u && (int32_t)(now_us - ctx->reply_due_us) >= 0) {
        uint16_t length = ctx->tx_length;
        if ((uint32_t)(now_us - ctx->reply_due_us) > PROTO_REPLY_EXPIRY_US ||
            ctx->rx_length != 0u) {
            cancel_reply(ctx);
            return;
        }
        ctx->pending = 0u;
        ctx->tx_length = 0u;
        if (ctx->send != 0) {
            ctx->send(ctx->user, ctx->tx, length);
            ++ctx->tx_packets;
        }
    }
}
