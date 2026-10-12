// Batch validator: reads N teams (one per line-delimited base64 blob),
// returns N verdicts. One process handles many teams — fast.
const {Dex} = require('/home/morgrad/pokemon-showdown/dist/sim/dex');
const {Teams} = require('/home/morgrad/pokemon-showdown/dist/sim/teams');
const {TeamValidator} = require('/home/morgrad/pokemon-showdown/dist/sim/team-validator');

const FORMAT = 'gen9championsvgc2026regmc';
const validator = TeamValidator.get(FORMAT);

let buf = '';
process.stdin.on('data', d => buf += d);
process.stdin.on('end', () => {
    const lines = buf.split('\n').filter(Boolean);
    for (const line of lines) {
        let team;
        try {
            const text = Buffer.from(line, 'base64').toString('utf-8');
            const parsed = Teams.import(text);
            if (!parsed) { console.log('PARSE_FAIL'); continue; }
            const errs = validator.validateTeam(parsed);
            if (errs === null) console.log('OK');
            else console.log('FAIL:' + errs[0]);
        } catch (e) {
            console.log('ERR:' + e.message);
        }
    }
});
