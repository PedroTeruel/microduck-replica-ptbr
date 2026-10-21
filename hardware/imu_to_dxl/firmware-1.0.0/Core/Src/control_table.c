#include "control_table.h"
#include "board.h"
#include "imu.h"
#include <string.h>

/* Feetech register map for this IMU board (ID 200), per
 * hardware/imu_to_dxl/总线协议.md. Bytes 0..9 are protocol-owned identity;
 * the 15-byte fast block at 56 is gyro + SFLP quaternion + counter + status +
 * reserved, sitting at the same address Feetech servos use for their status
 * block so one SYNC READ 56/15 fetches this board and every servo. */

/* Status bits (byte 13 of the block, address 69). Definitions from the
 * protocol spec section 4. */
#define STATUS_FUSION_NOT_READY   0x01u
#define STATUS_IMU_COMM_FAIL      0x02u
#define STATUS_SELF_TEST_FAIL     0x04u
#define STATUS_READER_TOO_SLOW    0x08u

/* Counter threshold for STATUS_READER_TOO_SLOW: the spec says "refreshed more
 * than 4 times since last read" => 5 or more refreshes trips the bit. */
#define SLOW_READER_REFRESHES     5u

static uint8_t user_marker; /* Address 85: RAM marker, there is no LED on PCB. */

/* Tracks how many SFLP records were accepted at the last read, so byte 13 bit 3
 * (reader too slow) can flag when the host polls slower than ~30 Hz. */
static uint32_t last_sample_count;

static void put16(uint8_t *p, uint16_t value) { p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8); }
static void put32(uint8_t *p, uint32_t value)
{ for (unsigned i = 0u; i < 4u; ++i) p[i] = (uint8_t)(value >> (8u * i)); }

static uint8_t status_bits(const imu_snapshot_t *s)
{
    uint8_t bits = 0u;
    if (!s->ready || (s->quat_fp16[0] == 0u && s->quat_fp16[1] == 0u && s->quat_fp16[2] == 0u)) {
        bits |= STATUS_FUSION_NOT_READY;
    }
    switch ((imu_error_t)s->error) {
    case IMU_ERROR_SPI:
    case IMU_ERROR_RESET_TIMEOUT:
    case IMU_ERROR_CONFIG:
    case IMU_ERROR_STALE:
    case IMU_ERROR_FIFO:
    case IMU_ERROR_QUAT:
        bits |= STATUS_IMU_COMM_FAIL;
        break;
    case IMU_ERROR_ID:
        bits |= STATUS_SELF_TEST_FAIL;
        break;
    default:
        break;
    }
    return bits;
}

uint8_t control_table_read(void *user, uint16_t address, uint16_t length, uint8_t *out)
{
    proto_context *protocol = (proto_context *)user;
    uint8_t table[256] = {0};
    imu_snapshot_t s;
    if (!out || !length || address >= 256u || length > 256u - address) return PROTO_ERR_RANGE;
    /* Both acquisition and this callback run in main, so this is an untorn snapshot. */
    imu_get_snapshot(&s);

    /* 56..70: 15-byte fast block (spec section 3). */
    for (unsigned i = 0u; i < 3u; ++i) {
        put16(&table[56u + i * 2u], (uint16_t)s.gyro[i]);
        put16(&table[62u + i * 2u], s.quat_fp16[i]);
    }
    table[68] = (uint8_t)s.sample_count;                       /* byte 12: sample counter */
    table[69] = status_bits(&s);                                /* byte 13: status bits */
    table[70] = 0u;                                             /* byte 14: reserved, must be 0 */

    /* Reader-too-slow: count how many SFLP records landed since the last read. */
    {
        uint32_t delta = s.sample_count - last_sample_count;
        if (delta >= SLOW_READER_REFRESHES) table[69] |= STATUS_READER_TOO_SLOW;
        last_sample_count = s.sample_count;
    }

    /* 71..76: raw accelerometer (our extension; not part of the 15-byte block). */
    for (unsigned i = 0u; i < 3u; ++i) {
        put16(&table[71u + i * 2u], (uint16_t)s.raw_accel[i]);
    }
    table[77] = s.who_am_i;
    table[78] = s.error;
    table[79] = board_diagnostics.clock_status;
    table[80] = BOARD_ENABLE_WATCHDOG;
    put32(&table[81], s.sample_count);
    table[85] = user_marker;

    /* 90..185: 96-byte lifetime diagnostic block, 24 little-endian u32 words.
     * Revision 1. Not servo telemetry; imu_probe consumes it for acceptance. */
    put32(&table[90], s.gyro_count);
    put32(&table[94], s.accel_count);
    put32(&table[98], board_millis());
    put32(&table[102], board_millis() - s.last_gyro_ms);
    put32(&table[106], board_millis() - s.last_quat_ms);
    put32(&table[110], s.spi_errors);
    put32(&table[114], s.fifo_overflows);
    put32(&table[118], s.invalid_quaternions);
    put32(&table[122], s.recovery_count);
    put32(&table[126], board_diagnostics.rx_overflows);
    put32(&table[130], board_diagnostics.uart_errors);
    put32(&table[134], protocol->checksum_errors);
    put32(&table[138], protocol->malformed_packets);
    put32(&table[142], protocol->receive_timeouts);
    put32(&table[146], protocol->rx_packets);
    put32(&table[150], board_diagnostics.tx_packets);
    put32(&table[154], protocol->cancelled_replies);
    put32(&table[158], board_diagnostics.reset_flags);
    put32(&table[162], board_diagnostics.clock_hz);
    put32(&table[166], board_diagnostics.tx_timeouts);
    put32(&table[170], board_diagnostics.log_dropped);
    put32(&table[174], 1u); /* Diagnostic map revision. */
    put32(&table[178], board_diagnostics.tx_busy_drops);
    memcpy(out, &table[address], length);
    return PROTO_OK;
}

uint8_t control_table_write(void *user, uint16_t address, uint16_t length, const uint8_t *data)
{
    (void)user;
    if (!data || length != 1u) return PROTO_ERR_ACCESS;
    if (address == 85u) { user_marker = data[0]; return PROTO_OK; }
    if (address == 240u && data[0] == 0xA5u) { imu_request_reinit(); return PROTO_OK; }
    return PROTO_ERR_ACCESS;
}
