// Templates: fill in the operator's real name and address before deploying publicly
// (an Impressum is required for German websites, § 5 DDG).
const OPERATOR = import.meta.env.VITE_OPERATOR_NAME ?? '[Your name]'
const ADDRESS = import.meta.env.VITE_OPERATOR_ADDRESS ?? '[Street, postcode, city]'
const CONTACT = import.meta.env.VITE_OPERATOR_EMAIL ?? '[contact email]'

export function ImpressumPage() {
  return (
    <section className="panel prose">
      <h1>Impressum</h1>
      <p>Angaben gemäß § 5 DDG</p>
      <p>{OPERATOR}<br />{ADDRESS}</p>
      <p>E-Mail: {CONTACT}</p>
      <p>
        Heimkommen is a private, non-commercial student project. It is not affiliated with, endorsed by or operated
        by Deutsche Bahn AG, NVBW or any transport company.
      </p>
    </section>
  )
}

export function PrivacyPage() {
  return (
    <section className="panel prose">
      <h1>Datenschutzerklärung / Privacy policy</h1>
      <h2>Controller</h2>
      <p>{OPERATOR}, {ADDRESS}, {CONTACT}</p>
      <h2>What we store</h2>
      <ul>
        <li><strong>Without an account:</strong> journey searches are processed to answer your request. We log the
          predicted probabilities together with the stations and times (no IP address, no account) to measure prediction
          accuracy. Server access logs are kept for at most 7 days for security.</li>
        <li><strong>With an account:</strong> your email address, a salted bcrypt hash of your password, and the trips you
          save (Art. 6(1)(b) GDPR).</li>
        <li><strong>Location:</strong> if you tap "nearest station", your browser sends your coordinates once to find the
          closest station. They are not stored.</li>
        <li>A login token is kept in your browser's local storage. No cookies, no tracking, no analytics.</li>
      </ul>
      <h2>Third parties</h2>
      <ul>
        <li>Map tiles are loaded from OpenStreetMap's tile servers only when you open a map; your IP address is
          transmitted to them (see the OSMF privacy policy).</li>
        <li>Live delay data is requested server-side from the DB Timetables API; none of your personal data is sent.</li>
      </ul>
      <h2>Your rights</h2>
      <p>
        You can delete your account and all saved trips at any time under "My trips". You have the right to access,
        rectification, erasure, restriction, portability and objection, and to lodge a complaint with a supervisory
        authority (in Baden-Württemberg: LfDI BW).
      </p>
    </section>
  )
}

export function DisclaimerPage() {
  return (
    <section className="panel prose">
      <h1>About the predictions</h1>
      <p>
        Probabilities come from a statistical model trained on historical delays and a simulation. They are estimates,
        not guarantees, and they can be wrong, especially during disruptions, construction work or strikes that the
        timetable does not reflect. Always check official sources before you travel.
      </p>
      <p>Buses and trams are assumed to run on time. Only train delays and cancellations are modelled.</p>
      <p>
        Data sources: timetable © NVBW (Nahverkehrsgesellschaft Baden-Württemberg), delay history from the piebro/deutsche-bahn-data
        dataset (CC BY 4.0, data by Deutsche Bahn), live data from the DB Timetables API. Map data © OpenStreetMap contributors.
      </p>
    </section>
  )
}
