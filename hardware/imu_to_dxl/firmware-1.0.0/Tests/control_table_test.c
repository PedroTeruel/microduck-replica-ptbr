#include "control_table.h"
#include "imu.h"
#include "board.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
board_diagnostics_t board_diagnostics;
static imu_snapshot_t sensor;
static unsigned restart_count;
void imu_get_snapshot(imu_snapshot_t *out) { *out = sensor; }
void imu_request_reinit(void) { ++restart_count; }
uint32_t board_millis(void) { return 123456u; }
int main(void)
{
    proto_context protocol = {0};
    uint8_t out[256] = {0};
    const uint8_t marker = 42, restart = 0xa5;
    /* Fast 15-byte block at address 56: gyro i16x3, qx/qy/qz fp16, counter,
     * status, reserved. Bytes 0..11 (gyro+quat) match the 12-byte window. */
    sensor.ready = sensor.configured = 1;
    sensor.gyro[0] = -32768; sensor.gyro[1] = 32767; sensor.gyro[2] = -1;
    sensor.quat_fp16[0] = 0x3800; sensor.quat_fp16[1] = 0xb800; sensor.quat_fp16[2] = 0x8000;
    sensor.sample_count = 0x12345678;
    sensor.who_am_i = 0x70;
    sensor.error = IMU_ERROR_NONE;
    assert(control_table_read(&protocol,56,12,out) == PROTO_OK);
    const uint8_t expected12[] = {0x00,0x80,0xff,0x7f,0xff,0xff,0x00,0x38,0x00,0xb8,0x00,0x80};
    assert(memcmp(out,expected12,sizeof(expected12)) == 0);
    /* Bytes 12..14: counter (low byte of sample_count), status bits, reserved=0. */
    assert(control_table_read(&protocol,68,3,out) == PROTO_OK);
    assert(out[0] == 0x78);                      /* sample counter low byte */
    assert(out[1] == 0);                          /* status: ready, no error */
    assert(out[2] == 0);                          /* reserved must be 0 */
    /* Status bits: not ready when snapshot isn't ready. */
    sensor.ready = 0;
    assert(control_table_read(&protocol,69,1,out) == PROTO_OK);
    assert(out[0] == 0x01);                       /* BIT0 fusion not ready */
    sensor.ready = 1;
    sensor.error = IMU_ERROR_ID;
    assert(control_table_read(&protocol,69,1,out) == PROTO_OK);
    assert(out[0] == 0x04);                       /* BIT2 self-test fail */
    sensor.error = IMU_ERROR_SPI;
    assert(control_table_read(&protocol,69,1,out) == PROTO_OK);
    assert(out[0] == 0x02);                       /* BIT1 IMU comm fail */
    sensor.error = IMU_ERROR_NONE;
    /* Extensions: who_am_i at 77, full sample_count u32 at 81..84. */
    assert(control_table_read(&protocol,77,1,out) == PROTO_OK);
    assert(out[0] == 0x70);
    assert(control_table_read(&protocol,81,4,out) == PROTO_OK);
    assert(out[0] == 0x78 && out[1] == 0x56 && out[2] == 0x34 && out[3] == 0x12);
    /* Accelerometer moved to 71..76. */
    sensor.raw_accel[0] = 0x1234; sensor.raw_accel[1] = -1; sensor.raw_accel[2] = 0;
    assert(control_table_read(&protocol,71,6,out) == PROTO_OK);
    assert(out[0] == 0x34 && out[1] == 0x12 && out[2] == 0xff && out[3] == 0xff);
    /* Diagnostic block starts at 90: gyro_count first word. */
    sensor.gyro_count = 0x11223344;
    assert(control_table_read(&protocol,90,4,out) == PROTO_OK);
    assert(out[0] == 0x44 && out[1] == 0x33 && out[2] == 0x22 && out[3] == 0x11);
    /* Revision word at 174, tx_busy_drops at 178: 96-byte block ends at 185. */
    assert(control_table_read(&protocol,174,8,out) == PROTO_OK);
    assert(out[0] == 1 && out[1] == 0 && out[2] == 0 && out[3] == 0);
    /* Range checks. */
    assert(control_table_read(&protocol,255,2,out) == PROTO_ERR_RANGE);
    assert(control_table_read(&protocol,0,0,out) == PROTO_ERR_RANGE);
    assert(control_table_read(&protocol,0,256,out) == PROTO_OK);
    /* Writable RAM marker (85) and IMU restart magic (240). */
    assert(control_table_write(&protocol,85,1,&marker) == PROTO_OK);
    assert(control_table_read(&protocol,85,1,out) == PROTO_OK && out[0] == marker);
    assert(control_table_write(&protocol,83,2,out) == PROTO_ERR_ACCESS);
    assert(control_table_write(&protocol,56,1,&marker) == PROTO_ERR_ACCESS);
    assert(control_table_write(&protocol,5,1,&marker) == PROTO_ERR_ACCESS);
    assert(control_table_write(&protocol,240,1,&marker) == PROTO_ERR_ACCESS);
    assert(control_table_write(&protocol,240,1,&restart) == PROTO_OK && restart_count == 1);
    puts("control table: 20 checks passed");
    return 0;
}
